"""
Celery tasks for fetching and processing football data using APIFootball.com
This module replaces the_odds_api tasks with more robust APIFootball integration.
"""

import logging
from django.conf import settings
from celery import chord, shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta, datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
import random
import time

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .utils import settle_ticket
from .apifootball_client import APIFootballClient, APIFootballException

from meta_integration.utils import send_whatsapp_message, create_text_message_data

logger = logging.getLogger(__name__)

# --- Configuration ---
APIFOOTBALL_ODDS_LEAD_TIME_DAYS = getattr(settings, 'APIFOOTBALL_LEAD_TIME_DAYS', 7)
APIFOOTBALL_EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'APIFOOTBALL_EVENT_DISCOVERY_STALENESS_HOURS', 6)
APIFOOTBALL_ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'APIFOOTBALL_UPCOMING_STALENESS_MINUTES', 60)
APIFOOTBALL_ASSUMED_COMPLETION_MINUTES = getattr(settings, 'APIFOOTBALL_ASSUMED_COMPLETION_MINUTES', 120)
APIFOOTBALL_MAX_EVENT_RETRIES = getattr(settings, 'APIFOOTBALL_MAX_EVENT_RETRIES', 3)
APIFOOTBALL_EVENT_RETRY_DELAY = getattr(settings, 'APIFOOTBALL_EVENT_RETRY_DELAY', 300)

# --- Helper Functions ---

@transaction.atomic
def _process_apifootball_odds_data(fixture: FootballFixture, odds_data: dict):
    """
    Processes and saves odds/market data from APIFootball for a fixture.
    
    APIFootball odds structure:
    {
        'match_id': '12345',
        'odd_bookmakers': [
            {
                'bookmaker_name': 'Bet365',
                'bookmaker_odds': [
                    {
                        'odd_1': '2.50',  # Home win
                        'odd_x': '3.10',  # Draw
                        'odd_2': '2.90',  # Away win
                    }
                ]
            }
        ]
    }
    """
    logger.debug(f"Processing odds data for fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name})")
    
    if not odds_data or 'odd_bookmakers' not in odds_data:
        logger.debug(f"No odds bookmakers data provided for fixture {fixture.id}")
        return
    
    bookmakers_count = len(odds_data.get('odd_bookmakers', []))
    logger.debug(f"Processing odds from {bookmakers_count} bookmaker(s)")
    
    total_markets_created = 0
    total_outcomes_created = 0
    
    for bookmaker_data in odds_data.get('odd_bookmakers', []):
        bookmaker_name = bookmaker_data.get('bookmaker_name', 'Unknown')
        
        # Create or get bookmaker
        bookmaker, bookmaker_created = Bookmaker.objects.get_or_create(
            api_bookmaker_key=bookmaker_name.lower().replace(' ', '_'),
            defaults={'name': bookmaker_name}
        )
        if bookmaker_created:
            logger.debug(f"Created new bookmaker: {bookmaker_name}")
        
        # Process odds (match winner - H2H market)
        for odds_entry in bookmaker_data.get('bookmaker_odds', []):
            odd_1 = odds_entry.get('odd_1')  # Home win
            odd_x = odds_entry.get('odd_x')  # Draw
            odd_2 = odds_entry.get('odd_2')  # Away win
            
            if odd_1 or odd_x or odd_2:
                # Create H2H market
                category, _ = MarketCategory.objects.get_or_create(name='Match Winner')
                
                # Delete old market if exists
                deleted_count, _ = Market.objects.filter(
                    fixture=fixture,
                    bookmaker=bookmaker,
                    api_market_key='h2h'
                ).delete()
                if deleted_count > 0:
                    logger.debug(f"Deleted {deleted_count} old market(s) for bookmaker {bookmaker_name}")
                
                market = Market.objects.create(
                    fixture=fixture,
                    bookmaker=bookmaker,
                    api_market_key='h2h',
                    category=category,
                    last_updated_odds_api=timezone.now()
                )
                total_markets_created += 1
                
                outcomes_to_create = []
                
                if odd_1:
                    outcomes_to_create.append(
                        MarketOutcome(
                            market=market,
                            outcome_name=fixture.home_team.name,
                            odds=Decimal(str(odd_1)),
                        )
                    )
                
                if odd_x:
                    outcomes_to_create.append(
                        MarketOutcome(
                            market=market,
                            outcome_name='Draw',
                            odds=Decimal(str(odd_x)),
                        )
                    )
                
                if odd_2:
                    outcomes_to_create.append(
                        MarketOutcome(
                            market=market,
                            outcome_name=fixture.away_team.name,
                            odds=Decimal(str(odd_2)),
                        )
                    )
                
                if outcomes_to_create:
                    MarketOutcome.objects.bulk_create(outcomes_to_create)
                    total_outcomes_created += len(outcomes_to_create)
                    logger.debug(f"Created market with {len(outcomes_to_create)} outcomes for bookmaker {bookmaker_name}")
    
    logger.debug(f"Odds processing complete for fixture {fixture.id}: {total_markets_created} markets, {total_outcomes_created} outcomes")

# --- PIPELINE 1: Full Data Update (Leagues, Events, Odds) ---

@shared_task(name="football_data_app.run_apifootball_full_update")
def run_apifootball_full_update_task():
    """Main entry point for the APIFootball data fetching pipeline."""
    logger.info("="*80)
    logger.info("TASK START: run_apifootball_full_update_task")
    logger.info("="*80)
    try:
        pipeline = (
            fetch_and_update_leagues_task.s() |
            _prepare_and_launch_event_odds_chord.s()
        )
        result = pipeline.apply_async()
        result_id = getattr(result, 'id', None)
        logger.info(f"Pipeline scheduled successfully with ID: {result_id or 'N/A'}")
        logger.info("TASK END: run_apifootball_full_update_task - Pipeline dispatched")
        return {"status": "dispatched", "pipeline_id": str(result_id) if result_id else None}
    except Exception as e:
        logger.error(f"TASK ERROR: run_apifootball_full_update_task failed with error: {e}", exc_info=True)
        raise

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self, _=None):
    """Step 1: Fetches all available football leagues from APIFootball."""
    logger.info("="*80)
    logger.info("TASK START: fetch_and_update_leagues_task (League Update Pipeline)")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    client = APIFootballClient()
    
    try:
        logger.info("Calling APIFootball.get_leagues()...")
        leagues_data = client.get_leagues()
        
        if not leagues_data:
            logger.warning("No leagues data received from APIFootball API.")
            logger.info("TASK END: fetch_and_update_leagues_task - No data")
            return []
        
        logger.info(f"Received {len(leagues_data)} leagues from APIFootball API")
        
        processed_league_ids = []
        created_count = 0
        updated_count = 0
        
        for idx, league_item in enumerate(leagues_data, 1):
            league_id = league_item.get('league_id')
            league_name = league_item.get('league_name')
            country_id = league_item.get('country_id')
            country_name = league_item.get('country_name')
            league_season = league_item.get('league_season')
            league_logo = league_item.get('league_logo')
            
            if not league_id or not league_name:
                logger.warning(f"Skipping league {idx} - missing league_id or league_name")
                continue
            
            # Store the league
            league_obj, created = League.objects.update_or_create(
                api_id=league_id,
                defaults={
                    'name': league_name,
                    'sport_key': 'soccer',
                    'sport_group_name': 'Football',
                    'short_name': league_name,
                    'country_id': country_id,
                    'country_name': country_name,
                    'league_season': league_season,
                    'logo_url': league_logo,
                    'active': True
                }
            )
            
            processed_league_ids.append(league_obj.id)
            
            if created:
                created_count += 1
                logger.info(f"Created new league: {league_name} (API ID: {league_id}, DB ID: {league_obj.id})")
            else:
                updated_count += 1
                logger.debug(f"Updated existing league: {league_name} (API ID: {league_id}, DB ID: {league_obj.id})")
        
        logger.info(f"League processing complete: {len(processed_league_ids)} total, {created_count} created, {updated_count} updated")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_and_update_leagues_task - SUCCESS")
        logger.info(f"Returning {len(processed_league_ids)} league IDs to next task")
        logger.info("="*80)
        return processed_league_ids
        
    except APIFootballException as e:
        logger.error(f"TASK ERROR: APIFootball API error during league update: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error during league update: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)

@shared_task(name="football_data_app.tasks._prepare_and_launch_event_odds_chord")
def _prepare_and_launch_event_odds_chord(league_ids: List[int]):
    """
    Intermediate task: Receives league_ids and launches event fetching chord.
    """
    logger.info("="*80)
    logger.info("TASK START: _prepare_and_launch_event_odds_chord")
    logger.info("="*80)
    
    if not league_ids:
        logger.warning("No league IDs received from previous task. Skipping event/odds processing.")
        logger.info("TASK END: _prepare_and_launch_event_odds_chord - No leagues to process")
        return
    
    logger.info(f"Received {len(league_ids)} league IDs from previous task: {league_ids}")
    logger.info(f"Preparing to fetch events for {len(league_ids)} leagues...")
    
    try:
        event_fetch_tasks_group = group([
            fetch_events_for_league_task.s(league_id) for league_id in league_ids
        ])
        
        odds_dispatch_callback = dispatch_odds_fetching_after_events_task.s()
        
        logger.info(f"Creating chord with {len(league_ids)} event fetch tasks...")
        task_chord = chord(event_fetch_tasks_group)(odds_dispatch_callback)
        result = task_chord.apply_async()
        
        logger.info(f"Chord dispatched successfully. Chord ID: {result.id if hasattr(result, 'id') else 'N/A'}")
        logger.info(f"Event fetch tasks will execute in parallel for {len(league_ids)} leagues")
        logger.info("After all event fetches complete, odds dispatch task will be triggered")
        logger.info("="*80)
        logger.info("TASK END: _prepare_and_launch_event_odds_chord - SUCCESS")
        logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Failed to create or dispatch chord: {e}", exc_info=True)
        raise

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id: int):
    """Fetches and updates events (fixtures) for a single league from APIFootball."""
    logger.info("="*80)
    logger.info(f"TASK START: fetch_events_for_league_task - League ID: {league_id}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    events_processed_count = 0
    
    try:
        logger.info(f"Fetching league from database (ID: {league_id})...")
        league = League.objects.get(id=league_id)
        logger.info(f"League found: {league.name} (API ID: {league.api_id})")
        
        client = APIFootballClient()
        
        logger.info(f"Calling APIFootball.get_upcoming_fixtures(league_id={league.api_id}, days_ahead={APIFOOTBALL_ODDS_LEAD_TIME_DAYS})...")
        fixtures_data = client.get_upcoming_fixtures(
            league_id=league.api_id,
            days_ahead=APIFOOTBALL_ODDS_LEAD_TIME_DAYS
        )
        
        logger.info(f"API returned {len(fixtures_data) if fixtures_data else 0} fixtures for league {league.name}")
        
        if fixtures_data:
            logger.info(f"Processing {len(fixtures_data)} fixtures for league {league.name}...")
            with transaction.atomic():
                for idx, fixture_item in enumerate(fixtures_data, 1):
                    match_id = fixture_item.get('match_id')
                    match_date = fixture_item.get('match_date')
                    match_time = fixture_item.get('match_time')
                    match_status = fixture_item.get('match_status', '')
                    
                    home_team_name = fixture_item.get('match_hometeam_name')
                    away_team_name = fixture_item.get('match_awayteam_name')
                    home_team_id = fixture_item.get('match_hometeam_id')
                    away_team_id = fixture_item.get('match_awayteam_id')
                    
                    if not match_id or not home_team_name or not away_team_name:
                        logger.warning(f"Skipping fixture {idx} - missing required data (match_id, home_team, or away_team)")
                        continue
                    
                    # Create or get teams
                    home_team, home_created = Team.objects.get_or_create(
                        name=home_team_name,
                        defaults={
                            'api_team_id': home_team_id,
                            'badge_url': fixture_item.get('team_home_badge')
                        }
                    )
                    if home_created:
                        logger.debug(f"Created new team: {home_team_name}")
                    
                    away_team, away_created = Team.objects.get_or_create(
                        name=away_team_name,
                        defaults={
                            'api_team_id': away_team_id,
                            'badge_url': fixture_item.get('team_away_badge')
                        }
                    )
                    if away_created:
                        logger.debug(f"Created new team: {away_team_name}")
                    
                    # Parse match datetime
                    match_datetime = None
                    if match_date and match_time:
                        try:
                            datetime_str = f"{match_date} {match_time}"
                            match_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                            # Make timezone aware
                            match_datetime = timezone.make_aware(match_datetime)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Could not parse match datetime: {datetime_str}, error: {e}")
                    
                    # Determine fixture status
                    status = FootballFixture.FixtureStatus.SCHEDULED
                    if match_status:
                        match_status_lower = match_status.lower()
                        if 'finished' in match_status_lower or 'ft' in match_status_lower:
                            status = FootballFixture.FixtureStatus.FINISHED
                        elif any(x in match_status_lower for x in ['live', "1st half", "2nd half", "halftime"]):
                            status = FootballFixture.FixtureStatus.LIVE
                        elif 'postponed' in match_status_lower:
                            status = FootballFixture.FixtureStatus.POSTPONED
                        elif 'cancelled' in match_status_lower or 'canceled' in match_status_lower:
                            status = FootballFixture.FixtureStatus.CANCELLED
                    
                    # Get scores if available
                    home_score = fixture_item.get('match_hometeam_score')
                    away_score = fixture_item.get('match_awayteam_score')
                    
                    # Clean up score values
                    try:
                        home_score = int(home_score) if home_score and home_score != '' else None
                    except (ValueError, TypeError):
                        home_score = None
                    
                    try:
                        away_score = int(away_score) if away_score and away_score != '' else None
                    except (ValueError, TypeError):
                        away_score = None
                    
                    # Create or update fixture
                    fixture, fixture_created = FootballFixture.objects.update_or_create(
                        api_id=match_id,
                        defaults={
                            'league': league,
                            'home_team': home_team,
                            'away_team': away_team,
                            'match_date': match_datetime,
                            'status': status,
                            'home_team_score': home_score,
                            'away_team_score': away_score,
                        }
                    )
                    events_processed_count += 1
                    
                    if fixture_created:
                        logger.debug(f"Created fixture: {home_team_name} vs {away_team_name} (Match ID: {match_id})")
                    else:
                        logger.debug(f"Updated fixture: {home_team_name} vs {away_team_name} (Match ID: {match_id})")
            
            logger.info(f"Successfully processed {events_processed_count} fixtures in database transaction")
        
        # Update league's last fetch timestamp
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Updated league.last_fetched_events timestamp for {league.name}")
        
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_task - SUCCESS")
        logger.info(f"League: {league.name}, Events Processed: {events_processed_count}")
        logger.info("="*80)
        return {"league_id": league_id, "status": "success", "events_processed": events_processed_count}
        
    except League.DoesNotExist:
        logger.error(f"TASK ERROR: League with ID {league_id} does not exist in database")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_task - FAILED (League not found)")
        logger.info("="*80)
        return {"league_id": league_id, "status": "error", "message": "League not found"}
    except APIFootballException as e:
        logger.error(f"TASK ERROR: APIFootball API error for league {league_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error fetching events for league {league_id}: {e}", exc_info=True)
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_task - FAILED")
        logger.info("="*80)
        return {"league_id": league_id, "status": "error", "message": str(e)}

@shared_task(bind=True)
def dispatch_odds_fetching_after_events_task(self, results_from_event_fetches):
    """
    Step 3: Dispatches individual tasks to fetch odds for each upcoming fixture.
    """
    logger.info("="*80)
    logger.info("TASK START: dispatch_odds_fetching_after_events_task (Odds Dispatch)")
    logger.info(f"Task ID: {self.request.id}")
    logger.info("="*80)
    
    logger.info(f"Received {len(results_from_event_fetches)} result(s) from event fetching group")
    logger.debug(f"Event fetch results: {results_from_event_fetches}")
    
    # Count successful events
    total_events_processed = 0
    for result in results_from_event_fetches:
        if isinstance(result, dict) and result.get('status') == 'success':
            total_events_processed += result.get('events_processed', 0)
    logger.info(f"Total events processed across all leagues: {total_events_processed}")
    
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=APIFOOTBALL_ODDS_UPCOMING_STALENESS_MINUTES)
    
    logger.info(f"Querying fixtures that need odds updates...")
    logger.info(f"Criteria: SCHEDULED status, match_date in next {APIFOOTBALL_ODDS_LEAD_TIME_DAYS} days, odds older than {APIFOOTBALL_ODDS_UPCOMING_STALENESS_MINUTES} minutes")
    
    # Get fixtures that need odds updates
    fixture_ids_to_update = FootballFixture.objects.filter(
        models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=stale_cutoff),
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=APIFOOTBALL_ODDS_LEAD_TIME_DAYS))
    ).values_list('id', flat=True)
    
    fixture_count = len(fixture_ids_to_update)
    
    if not fixture_ids_to_update:
        logger.info("No fixtures require an odds update at this time.")
        logger.info("="*80)
        logger.info("TASK END: dispatch_odds_fetching_after_events_task - No odds updates needed")
        logger.info("="*80)
        return
    
    logger.info(f"Found {fixture_count} fixtures requiring odds updates")
    logger.info(f"Creating {fixture_count} individual odds fetching tasks...")
    
    tasks = [fetch_odds_for_single_event_task.s(fixture_id) for fixture_id in fixture_ids_to_update]
    
    if tasks:
        group(tasks).apply_async()
        logger.info(f"Successfully dispatched {len(tasks)} odds fetching tasks to the queue")
        logger.info("Tasks will fetch odds for each fixture in parallel")
        logger.info("="*80)
        logger.info("TASK END: dispatch_odds_fetching_after_events_task - SUCCESS")
        logger.info(f"Dispatched {len(tasks)} odds fetch tasks")
        logger.info("="*80)

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_single_event_task(self, fixture_id: int):
    """Fetches odds for a single fixture from APIFootball."""
    # Add jitter to spread out API requests
    jitter_delay = random.uniform(0.5, 3.0)
    logger.debug(f"Applying jitter delay of {jitter_delay:.2f}s before fetching odds for fixture {fixture_id}")
    time.sleep(jitter_delay)
    
    logger.info(f"TASK START: fetch_odds_for_single_event_task - Fixture ID: {fixture_id}")
    
    try:
        logger.debug(f"Fetching fixture {fixture_id} from database...")
        fixture = FootballFixture.objects.select_related('league', 'home_team', 'away_team').get(id=fixture_id)
        logger.info(f"Fetching odds for: {fixture.home_team.name} vs {fixture.away_team.name} (API Match ID: {fixture.api_id})")
        
        client = APIFootballClient()
        
        logger.debug(f"Calling APIFootball.get_match_odds(match_id={fixture.api_id})...")
        odds_data = client.get_match_odds(match_id=fixture.api_id)
        
        if not odds_data:
            logger.info(f"No odds data returned from API for fixture {fixture.id}")
            fixture.last_odds_update = timezone.now()
            fixture.save(update_fields=['last_odds_update'])
            logger.info(f"TASK END: fetch_odds_for_single_event_task - No odds available")
            return {"fixture_id": fixture.id, "status": "no_odds_data"}
        
        logger.debug(f"Odds data received, processing...")
        with transaction.atomic():
            fixture_for_update = FootballFixture.objects.select_for_update().get(id=fixture.id)
            
            # Process odds data
            _process_apifootball_odds_data(fixture_for_update, odds_data)
            
            fixture_for_update.last_odds_update = timezone.now()
            fixture_for_update.save(update_fields=['last_odds_update'])
            
            logger.info(f"Successfully processed and saved odds for fixture {fixture.id}")
            logger.info(f"TASK END: fetch_odds_for_single_event_task - SUCCESS (Fixture: {fixture.id})")
            return {"fixture_id": fixture.id, "status": "success"}
    
    except FootballFixture.DoesNotExist:
        logger.error(f"TASK ERROR: Fixture with ID {fixture_id} not found in database")
        logger.info(f"TASK END: fetch_odds_for_single_event_task - FAILED (Fixture not found)")
        return {"fixture_id": fixture_id, "status": "error", "message": "Fixture not found"}
    except APIFootballException as e:
        logger.error(f"TASK ERROR: APIFootball API error for fixture {fixture_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error for fixture {fixture_id}: {e}", exc_info=True)
        raise self.retry(exc=e)

# --- PIPELINE 2: Score Fetching and Settlement ---

@shared_task(name="football_data_app.run_score_and_settlement_task")
def run_score_and_settlement_task():
    """Entry point for fetching scores and updating statuses."""
    logger.info("="*80)
    logger.info("TASK START: run_score_and_settlement_task (Score & Settlement Pipeline)")
    logger.info("="*80)
    
    try:
        logger.info("Fetching active leagues from database...")
        active_leagues = League.objects.filter(active=True).values_list('id', flat=True)
        league_count = len(active_leagues)
        
        logger.info(f"Found {league_count} active leagues")
        
        if not league_count:
            logger.warning("No active leagues found. Skipping score fetching.")
            logger.info("TASK END: run_score_and_settlement_task - No active leagues")
            return
        
        logger.info(f"Creating {league_count} score fetching tasks (one per league)...")
        tasks = [fetch_scores_for_league_task.s(league_id) for league_id in active_leagues]
        
        if tasks:
            group(tasks).apply_async()
            logger.info(f"Successfully dispatched {len(tasks)} score fetching tasks to the queue")
            logger.info("="*80)
            logger.info("TASK END: run_score_and_settlement_task - SUCCESS")
            logger.info(f"Dispatched {len(tasks)} tasks")
            logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Failed to dispatch score fetching tasks: {e}", exc_info=True)
        raise

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id: int):
    """
    Fetches live and finished match scores for a league from APIFootball.
    """
    logger.info("="*80)
    logger.info(f"TASK START: fetch_scores_for_league_task - League ID: {league_id}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    now = timezone.now()
    assumed_completion_cutoff = now - timedelta(minutes=APIFOOTBALL_ASSUMED_COMPLETION_MINUTES)
    
    try:
        logger.debug(f"Fetching league {league_id} from database...")
        league = League.objects.get(id=league_id)
        logger.info(f"Processing scores for league: {league.name} (API ID: {league.api_id})")
        
        # Get fixtures that need score updates (live or recently started)
        logger.debug("Querying fixtures that need score updates...")
        fixtures_to_check_qs = FootballFixture.objects.filter(
            league=league
        ).filter(
            models.Q(status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(
                status=FootballFixture.FixtureStatus.SCHEDULED,
                match_date__lt=now
            )
        )
        
        fixture_count = fixtures_to_check_qs.count()
        logger.info(f"Found {fixture_count} fixtures requiring score updates (LIVE or past SCHEDULED)")
        
        if not fixtures_to_check_qs.exists():
            logger.info(f"No fixtures need a score update for league {league.name}.")
            logger.info("="*80)
            logger.info("TASK END: fetch_scores_for_league_task - No updates needed")
            logger.info("="*80)
            return
        
        client = APIFootballClient()
        
        logger.info(f"Calling APIFootball.get_live_scores()...")
        live_scores = client.get_live_scores()
        logger.info(f"Received {len(live_scores) if live_scores else 0} live scores from API")
        
        # Get finished matches from the past few days
        date_from = (now - timedelta(days=2)).strftime('%Y-%m-%d')
        date_to = now.strftime('%Y-%m-%d')
        logger.info(f"Calling APIFootball.get_finished_matches(league_id={league.api_id}, from={date_from}, to={date_to})...")
        finished_matches = client.get_finished_matches(
            league_id=league.api_id,
            date_from=date_from,
            date_to=date_to
        )
        logger.info(f"Received {len(finished_matches) if finished_matches else 0} finished matches from API")
        
        # Combine live and finished matches
        all_scores = []
        if live_scores:
            all_scores.extend(live_scores)
        if finished_matches:
            all_scores.extend(finished_matches)
        
        # Filter to only matches from this league
        league_scores = [s for s in all_scores if s.get('league_id') == league.api_id]
        logger.info(f"Total scores for this league after filtering: {len(league_scores)}")
        
        processed_api_ids = set()
        fixtures_updated = 0
        fixtures_finished = 0
        fixtures_live = 0
        
        if league_scores:
            logger.info(f"Processing {len(league_scores)} score updates...")
            for idx, score_item in enumerate(league_scores, 1):
                match_id = score_item.get('match_id')
                if not match_id:
                    logger.warning(f"Score item {idx} missing match_id, skipping")
                    continue
                
                processed_api_ids.add(match_id)
                
                try:
                    with transaction.atomic():
                        fixture = FootballFixture.objects.select_for_update().get(api_id=match_id)
                        
                        if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                            logger.debug(f"Fixture {fixture.id} already FINISHED, skipping")
                            continue
                        
                        # Get scores
                        home_score = score_item.get('match_hometeam_score')
                        away_score = score_item.get('match_awayteam_score')
                        match_status = score_item.get('match_status', '').lower()
                        
                        # Parse scores
                        try:
                            home_score = int(home_score) if home_score and home_score != '' else None
                        except (ValueError, TypeError):
                            home_score = None
                        
                        try:
                            away_score = int(away_score) if away_score and away_score != '' else None
                        except (ValueError, TypeError):
                            away_score = None
                        
                        # Update scores if available
                        if home_score is not None:
                            fixture.home_team_score = home_score
                        if away_score is not None:
                            fixture.away_team_score = away_score
                        
                        fixture.last_score_update = timezone.now()
                        
                        # Update status
                        if 'finished' in match_status or 'ft' in match_status:
                            fixture.status = FootballFixture.FixtureStatus.FINISHED
                            fixture.save(update_fields=['home_team_score', 'away_team_score', 'status', 'last_score_update'])
                            fixtures_finished += 1
                            logger.info(f"Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) marked FINISHED. Score: {home_score}-{away_score}")
                            logger.info(f"Triggering settlement pipeline for fixture {fixture.id}...")
                            settle_fixture_pipeline_task.delay(fixture.id)
                        else:
                            fixture.status = FootballFixture.FixtureStatus.LIVE
                            fixture.save(update_fields=['home_team_score', 'away_team_score', 'status', 'last_score_update'])
                            fixtures_live += 1
                            logger.debug(f"Fixture {fixture.id} is LIVE. Score: {home_score}-{away_score}")
                        
                        fixtures_updated += 1
                
                except FootballFixture.DoesNotExist:
                    logger.warning(f"Received score data for unknown fixture API ID: {match_id}")
        
        # Handle fixtures past assumed completion time
        unprocessed_fixtures = fixtures_to_check_qs.exclude(api_id__in=processed_api_ids)
        unprocessed_count = unprocessed_fixtures.count()
        
        if unprocessed_count > 0:
            logger.info(f"Checking {unprocessed_count} unprocessed fixtures for assumed completion...")
            fixtures_assumed_finished = 0
            
            for fixture in unprocessed_fixtures:
                if fixture.match_date and fixture.match_date < assumed_completion_cutoff:
                    with transaction.atomic():
                        fixture_to_finish = FootballFixture.objects.select_for_update().get(id=fixture.id)
                        
                        if fixture_to_finish.status == FootballFixture.FixtureStatus.FINISHED:
                            continue
                        
                        if fixture_to_finish.home_team_score is None:
                            fixture_to_finish.home_team_score = 0
                        if fixture_to_finish.away_team_score is None:
                            fixture_to_finish.away_team_score = 0
                        
                        fixture_to_finish.status = FootballFixture.FixtureStatus.FINISHED
                        fixture_to_finish.last_score_update = timezone.now()
                        fixture_to_finish.save(update_fields=['home_team_score', 'away_team_score', 'status', 'last_score_update'])
                        
                        fixtures_assumed_finished += 1
                        logger.warning(
                            f"Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) "
                            f"not in API response and past assumed completion time. "
                            f"Marking FINISHED with score: {fixture_to_finish.home_team_score}-{fixture_to_finish.away_team_score}"
                        )
                        settle_fixture_pipeline_task.delay(fixture.id)
            
            if fixtures_assumed_finished > 0:
                logger.info(f"Marked {fixtures_assumed_finished} fixtures as assumed finished")
        
        logger.info("="*80)
        logger.info(f"TASK END: fetch_scores_for_league_task - SUCCESS")
        logger.info(f"League: {league.name}, Updated: {fixtures_updated}, Finished: {fixtures_finished}, Live: {fixtures_live}")
        logger.info("="*80)
    
    except League.DoesNotExist:
        logger.error(f"TASK ERROR: League {league_id} not found in database")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_scores_for_league_task - FAILED (League not found)")
        logger.info("="*80)
    except APIFootballException as e:
        logger.error(f"TASK ERROR: APIFootball API error for league {league_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error fetching scores for league {league_id}: {e}", exc_info=True)
        raise self.retry(exc=e)

# --- Settlement Tasks (reused from original tasks.py) ---

@shared_task(name="football_data_app.process_ticket_settlement_task")
def process_ticket_settlement_task(ticket_id: int):
    """Process settlement of a single bet ticket."""
    logger.info(f"Starting settlement process for BetTicket ID: {ticket_id}")
    try:
        settle_ticket(ticket_id)
    except Exception as e:
        logger.error(f"Error during settlement for BetTicket ID {ticket_id}: {e}", exc_info=True)

@shared_task(name="football_data_app.process_ticket_settlement_batch_task")
def process_ticket_settlement_batch_task(ticket_ids: List[int]):
    """Process a batch of bet tickets for settlement."""
    logger.info(f"Processing settlement for a batch of {len(ticket_ids)} tickets.")
    for ticket_id in ticket_ids:
        try:
            settle_ticket(ticket_id)
        except Exception as e:
            logger.error(f"Error during batch settlement for BetTicket ID {ticket_id}: {e}", exc_info=True)

@shared_task(bind=True, name="football_data_app.reconcile_and_settle_pending_items")
def reconcile_and_settle_pending_items_task(self):
    """Periodic task to find and settle any bets or tickets that might have been missed."""
    logger.info("[Reconciliation] START - Running reconciliation and settlement task.")
    
    now = timezone.now()
    stuck_fixture_cutoff = now - timedelta(minutes=APIFOOTBALL_ASSUMED_COMPLETION_MINUTES)
    
    # Find and force-settle stuck fixtures
    stuck_fixtures_qs = FootballFixture.objects.filter(
        markets__outcomes__bets__status='PENDING'
    ).filter(
        status__in=[FootballFixture.FixtureStatus.SCHEDULED, FootballFixture.FixtureStatus.LIVE],
        match_date__lt=stuck_fixture_cutoff
    ).distinct()
    
    stuck_fixtures_triggered_count = 0
    if stuck_fixtures_qs.exists():
        logger.warning(f"[Reconciliation] Found {stuck_fixtures_qs.count()} stuck fixtures with pending bets.")
        for fixture in stuck_fixtures_qs:
            with transaction.atomic():
                fixture_to_settle = FootballFixture.objects.select_for_update().get(id=fixture.id)
                if fixture_to_settle.status not in [FootballFixture.FixtureStatus.SCHEDULED, FootballFixture.FixtureStatus.LIVE]:
                    continue
                
                logger.warning(f"[Reconciliation] Force-settling stuck fixture ID: {fixture.id}.")
                if fixture_to_settle.home_team_score is None:
                    fixture_to_settle.home_team_score = 0
                if fixture_to_settle.away_team_score is None:
                    fixture_to_settle.away_team_score = 0
                
                fixture_to_settle.status = FootballFixture.FixtureStatus.FINISHED
                fixture_to_settle.save(update_fields=['status', 'home_team_score', 'away_team_score'])
                
                settle_fixture_pipeline_task.delay(fixture_to_settle.id)
                stuck_fixtures_triggered_count += 1
    
    # Settle individual bets whose outcomes are resolved
    bets_to_settle_qs = Bet.objects.filter(
        status='PENDING',
        market_outcome__result_status__in=[
            MarketOutcome.ResultStatus.WON,
            MarketOutcome.ResultStatus.LOST,
            MarketOutcome.ResultStatus.PUSH
        ]
    ).select_related('market_outcome')
    
    bets_updated_count = 0
    if bets_to_settle_qs.exists():
        with transaction.atomic():
            bets_to_update_list = []
            for bet in bets_to_settle_qs:
                bet.status = bet.market_outcome.result_status
                bets_to_update_list.append(bet)
            
            if bets_to_update_list:
                Bet.objects.bulk_update(bets_to_update_list, ['status'])
                bets_updated_count = len(bets_to_update_list)
    
    # Settle bet tickets
    ticket_ids_to_check = list(BetTicket.objects.filter(status='PENDING').values_list('id', flat=True))
    
    tickets_settled_count = 0
    if ticket_ids_to_check:
        process_ticket_settlement_batch_task.chunks(zip(ticket_ids_to_check), 100).apply_async()
        tickets_settled_count = len(ticket_ids_to_check)
    
    logger.info(f"[Reconciliation] FINISHED - Stuck: {stuck_fixtures_triggered_count}, Bets: {bets_updated_count}, Tickets: {tickets_settled_count}")

@shared_task(name="football_data_app.settle_fixture_pipeline")
def settle_fixture_pipeline_task(fixture_id: int):
    """Creates settlement chain for a finished fixture."""
    logger.info(f"Initiating settlement pipeline for fixture ID: {fixture_id}")
    pipeline = chain(
        settle_outcomes_for_fixture_task.s(fixture_id),
        settle_bets_for_fixture_task.s(),
        settle_tickets_for_fixture_task.s()
    )
    pipeline.apply_async()

@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id):
    """Settles market outcomes for a finished fixture."""
    logger.info(f"Settling outcomes for fixture ID: {fixture_id}")
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, status=FootballFixture.FixtureStatus.FINISHED)
        
        if fixture.home_team_score is None or fixture.away_team_score is None:
            logger.error(f"Cannot settle outcomes for fixture ID {fixture_id} - missing score data.")
            return
        
        home_score, away_score = fixture.home_team_score, fixture.away_team_score
        outcomes_to_update = []
        
        for market in fixture.markets.prefetch_related('outcomes'):
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'LOST'
                
                if market.api_market_key == 'h2h':
                    if ((outcome.outcome_name == fixture.home_team.name and home_score > away_score) or
                        (outcome.outcome_name == fixture.away_team.name and away_score > home_score) or
                        (outcome.outcome_name.lower() == 'draw' and home_score == away_score)):
                        new_status = 'WON'
                
                elif market.api_market_key in ['totals', 'alternate_totals'] and hasattr(outcome, 'point_value') and outcome.point_value is not None:
                    total_score = home_score + away_score
                    if 'over' in outcome.outcome_name.lower():
                        if total_score > outcome.point_value:
                            new_status = 'WON'
                        elif total_score == outcome.point_value:
                            new_status = 'PUSH'
                    elif 'under' in outcome.outcome_name.lower():
                        if total_score < outcome.point_value:
                            new_status = 'WON'
                        elif total_score == outcome.point_value:
                            new_status = 'PUSH'
                
                elif market.api_market_key == 'btts':
                    if ((outcome.outcome_name == 'Yes' and home_score > 0 and away_score > 0) or
                        (outcome.outcome_name == 'No' and not (home_score > 0 and away_score > 0))):
                        new_status = 'WON'
                
                if new_status != 'PENDING':
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)
        
        if outcomes_to_update:
            MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
        
        logger.info(f"Settled {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
    except FootballFixture.DoesNotExist:
        logger.warning(f"Fixture {fixture_id} not found for outcome settlement.")
    except Exception as e:
        logger.exception(f"Error settling outcomes for fixture {fixture_id}: {e}")
        raise self.retry(exc=e)
    return fixture_id

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id: int):
    """Settles individual bets based on outcomes."""
    if not fixture_id:
        return
    logger.info(f"Settling bets for fixture ID: {fixture_id}")
    try:
        bets_to_update = []
        for bet in Bet.objects.filter(
            market_outcome__market__fixture_id=fixture_id,
            status='PENDING'
        ).select_related('market_outcome'):
            if bet.market_outcome.result_status != 'PENDING':
                bet.status = bet.market_outcome.result_status
                bets_to_update.append(bet)
        
        if bets_to_update:
            Bet.objects.bulk_update(bets_to_update, ['status'])
            logger.info(f"Settled {len(bets_to_update)} bets for fixture {fixture_id}.")
        
        return fixture_id
    except Exception as e:
        logger.exception(f"Error settling bets for fixture {fixture_id}")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_bet_ticket_settlement_notification_task(self, ticket_id: int, new_status: str, winnings: str = "0.00"):
    """Sends WhatsApp notification about ticket status change."""
    logger.info(f"Sending settlement notification for BetTicket ID: {ticket_id}, Status: {new_status}")
    try:
        ticket = BetTicket.objects.select_related('user__customer_profile__contact', 'user__wallet').get(pk=ticket_id)
        
        # Check if user has customer profile and contact
        if not hasattr(ticket.user, 'customer_profile') or not ticket.user.customer_profile.contact:
            logger.warning(f"Cannot send notification - no contact found for ticket {ticket_id}.")
            return
        
        contact = ticket.user.customer_profile.contact
        
        if new_status == 'WON':
            message_body = (
                f"🎉 Congratulations! Your bet ticket (ID: {ticket.id}) has WON!\n\n"
                f"Amount Won: ${Decimal(winnings):.2f}\n"
                f"Your wallet has been credited. New balance: ${ticket.user.wallet.balance:.2f}."
            )
        elif new_status == 'LOST':
            message_body = (
                f"😔 Unfortunately, your bet ticket (ID: {ticket.id}) has lost.\n\n"
                f"Better luck next time! Type 'fixtures' to see upcoming matches."
            )
        elif new_status == 'REFUNDED':
            message_body = (
                f"ℹ️ Your bet ticket (ID: {ticket.id}) has been refunded.\n\n"
                f"The match result was a push/void. Your stake of ${Decimal(winnings):.2f} has been returned to your wallet.\n"
                f"New balance: ${ticket.user.wallet.balance:.2f}"
            )
        else:
            logger.warning(f"Unhandled status '{new_status}' for ticket {ticket_id}.")
            return
        
        message_data = create_text_message_data(text_body=message_body)
        send_whatsapp_message(to_phone_number=contact.whatsapp_id, message_type='text', data=message_data)
        logger.info(f"Sent settlement notification to {contact.whatsapp_id} for ticket {ticket_id}.")
    
    except BetTicket.DoesNotExist:
        logger.error(f"BetTicket {ticket_id} not found for notification.")
    except AttributeError as e:
        logger.error(f"Missing attribute when sending notification for ticket {ticket_id}: {e}", exc_info=True)
    except Exception as e:
        logger.exception(f"Error sending notification for ticket {ticket_id}: {e}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id: int):
    """Settles bet tickets based on bet statuses."""
    if not fixture_id:
        return
    logger.info(f"Settling tickets for fixture ID: {fixture_id}")
    try:
        affected_ticket_ids = list(BetTicket.objects.filter(
            status='PENDING',
            bets__market_outcome__market__fixture_id=fixture_id
        ).distinct().values_list('id', flat=True))
        
        if not affected_ticket_ids:
            logger.info(f"No pending tickets found for fixture {fixture_id}.")
            return
        
        process_ticket_settlement_batch_task.chunks(zip(affected_ticket_ids), 100).apply_async()
        logger.info(f"Dispatched settlement for {len(affected_ticket_ids)} tickets for fixture {fixture_id}.")
    except Exception as e:
        logger.exception(f"Error settling tickets for fixture {fixture_id}")
        raise self.retry(exc=e)
