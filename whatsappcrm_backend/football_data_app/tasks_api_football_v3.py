"""
Celery tasks for fetching and processing football data using API-Football v3 (api-football.com)
This module provides robust tasks for the new recommended API-Football v3 provider.
"""

import logging
from django.conf import settings
from celery import chord, shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from datetime import timedelta, datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
import random
import time

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .utils import settle_ticket
from .api_football_v3_client import APIFootballV3Client, APIFootballV3Exception

from meta_integration.utils import send_whatsapp_message, create_text_message_data

logger = logging.getLogger(__name__)

# --- Configuration ---
API_FOOTBALL_V3_LEAD_TIME_DAYS = getattr(settings, 'API_FOOTBALL_V3_LEAD_TIME_DAYS', 7)
API_FOOTBALL_V3_EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'API_FOOTBALL_V3_EVENT_DISCOVERY_STALENESS_HOURS', 6)
API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES = getattr(settings, 'API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES', 60)
API_FOOTBALL_V3_ASSUMED_COMPLETION_MINUTES = getattr(settings, 'API_FOOTBALL_V3_ASSUMED_COMPLETION_MINUTES', 120)
API_FOOTBALL_V3_MAX_EVENT_RETRIES = getattr(settings, 'API_FOOTBALL_V3_MAX_EVENT_RETRIES', 3)
API_FOOTBALL_V3_EVENT_RETRY_DELAY = getattr(settings, 'API_FOOTBALL_V3_EVENT_RETRY_DELAY', 300)

# Bet types to fetch from API-Football v3
# Note: Bet ID 6 is skipped as it's reserved but not commonly documented
API_FOOTBALL_BET_IDS = [1, 2, 3, 4, 5, 7, 8, 9]

# Setup command reference for consistent messaging
LEAGUE_SETUP_COMMAND = "python manage.py football_league_setup_v3"
LEAGUE_SETUP_COMMAND_DOCKER = "docker-compose exec backend python manage.py football_league_setup_v3"

# --- Helper Functions ---

def get_current_season() -> int:
    """
    Get the current season from Configuration model or fallback to settings/default.
    
    Priority:
    1. Database Configuration (provider_name='API-Football', is_active=True)
    2. Settings API_FOOTBALL_V3_CURRENT_SEASON
    3. Default: 2024
    
    Returns:
        Current season year as integer
    """
    try:
        from .models import Configuration
        config = Configuration.objects.filter(
            provider_name="API-Football",
            is_active=True
        ).first()
        if config and config.current_season:
            logger.debug(f"Current season loaded from database Configuration: {config.current_season}")
            return config.current_season
    except Exception as e:
        logger.warning(f"Could not load season from database Configuration: {e}")
    
    # Fallback to settings
    season = getattr(settings, 'API_FOOTBALL_V3_CURRENT_SEASON', 2024)
    logger.debug(f"Current season loaded from settings: {season}")
    return season


def parse_api_football_v3_datetime(timestamp_str: str) -> Optional[datetime]:
    """
    Parse datetime from API-Football v3 format.
    
    Per API-Football v3 documentation: https://www.api-football.com/documentation-v3
    - Timestamps are in ISO 8601 format (e.g., '2024-01-15T20:00:00+00:00')
    
    Args:
        timestamp_str: ISO 8601 timestamp string from the API
        
    Returns:
        Timezone-aware datetime object or None if parsing fails
    """
    if not timestamp_str:
        return None
    
    try:
        # Parse ISO 8601 format
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Could not parse datetime: {timestamp_str}, error: {e}")
        return None


@transaction.atomic
def _process_api_football_v3_odds_data(fixture: FootballFixture, odds_data: List[dict]):
    """
    Processes and saves odds/market data from API-Football v3 for a fixture.
    
    API-Football v3 odds structure:
    {
        'fixture': {'id': 12345},
        'league': {'id': 39, 'name': 'Premier League'},
        'bookmakers': [
            {
                'id': 8,
                'name': 'bet365',
                'bets': [
                    {
                        'id': 1,
                        'name': 'Match Winner',
                        'values': [
                            {'value': 'Home', 'odd': '2.50'},
                            {'value': 'Draw', 'odd': '3.10'},
                            {'value': 'Away', 'odd': '2.90'}
                        ]
                    }
                ]
            }
        ]
    }
    """
    logger.info(f"Processing odds data for fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name})")
    
    if not odds_data:
        logger.warning(f"No odds data provided for fixture {fixture.id}")
        return
    
    logger.info(f"Found {len(odds_data)} odds items to process")
    total_markets_created = 0
    total_outcomes_created = 0
    bookmakers_encountered = 0
    bookmakers_created = 0
    
    for odds_item in odds_data:
        bookmakers_list = odds_item.get('bookmakers', [])
        logger.info(f"Processing {len(bookmakers_list)} bookmakers for fixture {fixture.id}")
        
        for bookmaker_data in bookmakers_list:
            bookmaker_name = bookmaker_data.get('name', 'Unknown')
            bookmaker_id = bookmaker_data.get('id')
            
            # Create or get bookmaker
            bookmaker, bookmaker_created = Bookmaker.objects.get_or_create(
                api_bookmaker_key=str(bookmaker_id) if bookmaker_id else bookmaker_name.lower().replace(' ', '_'),
                defaults={'name': bookmaker_name}
            )
            bookmakers_encountered += 1
            if bookmaker_created:
                logger.info(f"Created new bookmaker: {bookmaker_name}")
                bookmakers_created += 1
            
            # Process bets (markets)
            bets_list = bookmaker_data.get('bets', [])
            logger.debug(f"Processing {len(bets_list)} markets for bookmaker {bookmaker_name}")
            
            for bet_data in bets_list:
                bet_name = bet_data.get('name', 'Unknown Market')
                bet_id = bet_data.get('id')
                
                # Map bet names and IDs to our categories and api_market_keys
                # Based on API-Football v3 documentation: https://www.api-football.com/documentation-v3
                if (bet_name == 'Match Winner' or bet_id == 1):
                    category, _ = MarketCategory.objects.get_or_create(name='Match Winner')
                    api_market_key = 'h2h'
                elif (bet_name == 'Double Chance' or bet_id == 2):
                    category, _ = MarketCategory.objects.get_or_create(name='Double Chance')
                    api_market_key = 'double_chance'
                elif (('Asian Handicap' in bet_name or 'Handicap' in bet_name) or bet_id == 3):
                    category, _ = MarketCategory.objects.get_or_create(name='Asian Handicap')
                    api_market_key = 'handicap'
                elif ('Draw No Bet' in bet_name or bet_id == 4):
                    category, _ = MarketCategory.objects.get_or_create(name='Draw No Bet')
                    api_market_key = 'draw_no_bet'
                elif (('Goals' in bet_name and 'Over' in bet_name) or bet_id == 5):
                    category, _ = MarketCategory.objects.get_or_create(name='Totals')
                    api_market_key = 'totals'
                elif ('Odd/Even' in bet_name or bet_id == 7):
                    category, _ = MarketCategory.objects.get_or_create(name='Odd/Even Goals')
                    api_market_key = 'odd_even'
                elif ('Both Teams Score' in bet_name or bet_id == 8):
                    category, _ = MarketCategory.objects.get_or_create(name='Both Teams To Score')
                    api_market_key = 'btts'
                elif (('Exact Score' in bet_name or 'Correct Score' in bet_name) or bet_id == 9):
                    category, _ = MarketCategory.objects.get_or_create(name='Correct Score')
                    api_market_key = 'correct_score'
                else:
                    # Generic category for other markets
                    category, _ = MarketCategory.objects.get_or_create(name=bet_name)
                    api_market_key = f"bet_{bet_id}" if bet_id else bet_name.lower().replace(' ', '_')
                
                # Delete old market if exists (to update odds)
                deleted_count, _ = Market.objects.filter(
                    fixture=fixture,
                    bookmaker=bookmaker,
                    api_market_key=api_market_key
                ).delete()
                if deleted_count > 0:
                    logger.debug(f"Deleted {deleted_count} old market(s) for bookmaker {bookmaker_name}, market {bet_name}")
                
                # Create new market
                market = Market.objects.create(
                    fixture=fixture,
                    bookmaker=bookmaker,
                    api_market_key=api_market_key,
                    category=category,
                    last_updated_odds_api=timezone.now()
                )
                total_markets_created += 1
                
                # Process outcomes (values)
                outcomes_to_create = []
                for value_data in bet_data.get('values', []):
                    outcome_value = value_data.get('value')
                    odd = value_data.get('odd')
                    
                    if outcome_value and odd:
                        try:
                            outcome_name = outcome_value
                            point_value = None
                            
                            # Map Home/Away to actual team names for relevant markets
                            if api_market_key in ['h2h', 'draw_no_bet']:
                                if outcome_value == 'Home':
                                    outcome_name = fixture.home_team.name
                                elif outcome_value == 'Away':
                                    outcome_name = fixture.away_team.name
                            
                            # Extract point values for totals and handicap markets
                            # API-Football v3 format: "Over 2.5", "Under 2.5", "Home -1.5", "Away +1.5"
                            if api_market_key in ['totals', 'handicap']:
                                parts = outcome_value.split()
                                if len(parts) >= 2:
                                    try:
                                        # Try to parse the last part as a number (handles +/- signs)
                                        point_str = parts[-1]
                                        point_value = float(point_str)
                                        # For handicap, map Home/Away to team names
                                        if api_market_key == 'handicap':
                                            if parts[0] == 'Home':
                                                outcome_name = fixture.home_team.name
                                            elif parts[0] == 'Away':
                                                outcome_name = fixture.away_team.name
                                        else:
                                            # For totals, keep "Over" or "Under" as name
                                            outcome_name = parts[0]
                                    except (ValueError, IndexError) as e:
                                        logger.debug(f"Could not parse point value from '{outcome_value}' for market '{bet_name}': {e}")
                            
                            outcomes_to_create.append(
                                MarketOutcome(
                                    market=market,
                                    outcome_name=outcome_name,
                                    odds=Decimal(str(odd)),
                                    point_value=point_value
                                )
                            )
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Could not parse odd value: {odd}, error: {e}")
                
                if outcomes_to_create:
                    MarketOutcome.objects.bulk_create(outcomes_to_create)
                    total_outcomes_created += len(outcomes_to_create)
                    logger.debug(f"Created market '{bet_name}' with {len(outcomes_to_create)} outcomes for bookmaker {bookmaker_name}")
                else:
                    logger.warning(f"No valid outcomes created for market '{bet_name}' from bookmaker {bookmaker_name}")
    
    logger.info(f"✓ Odds processing complete for fixture {fixture.id}: {bookmakers_encountered} bookmakers ({bookmakers_created} new), {total_markets_created} markets, {total_outcomes_created} outcomes")


# --- PIPELINE 1: Full Data Update (Leagues, Events, Odds) ---

@shared_task(name="football_data_app.run_api_football_v3_full_update", queue='cpu_heavy')
def run_api_football_v3_full_update_task():
    """Main entry point for the API-Football v3 data fetching pipeline."""
    logger.info("="*80)
    logger.info("TASK START: run_api_football_v3_full_update_task")
    logger.info("="*80)
    try:
        pipeline = (
            fetch_and_update_leagues_v3_task.s() |
            _prepare_and_launch_event_odds_chord_v3.s()
        )
        result = pipeline.apply_async()
        logger.info(f"Pipeline scheduled successfully with ID: {result.id if hasattr(result, 'id') else 'N/A'}")
        logger.info("TASK END: run_api_football_v3_full_update_task - Pipeline dispatched")
        return {"status": "dispatched", "pipeline_id": str(result.id) if hasattr(result, 'id') else None}
    except Exception as e:
        logger.error(f"TASK ERROR: run_api_football_v3_full_update_task failed with error: {e}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300, queue='cpu_heavy')
def fetch_and_update_leagues_v3_task(self, _=None):
    """Step 1: Fetches all available football leagues from API-Football v3."""
    logger.info("="*80)
    logger.info("TASK START: fetch_and_update_leagues_v3_task (League Update Pipeline)")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    client = APIFootballV3Client()
    
    try:
        logger.info("Calling APIFootballV3Client.get_leagues()...")
        leagues_data = client.get_leagues()
        
        if not leagues_data:
            logger.warning("No leagues data received from API-Football v3 API.")
            logger.info("TASK END: fetch_and_update_leagues_v3_task - No data")
            return []
        
        logger.info(f"Received {len(leagues_data)} leagues from API-Football v3 API")
        
        processed_league_ids = []
        created_count = 0
        updated_count = 0
        
        for idx, league_item in enumerate(leagues_data, 1):
            league_id = league_item.get('league', {}).get('id')
            league_name = league_item.get('league', {}).get('name')
            country_name = league_item.get('country', {}).get('name')
            league_logo = league_item.get('league', {}).get('logo')
            
            if not league_id or not league_name:
                logger.warning(f"Skipping league {idx} - missing league ID or name")
                continue
            
            # Store the league with v3_ prefix to distinguish from legacy
            api_id_str = f"v3_{league_id}"
            
            league_obj, created = League.objects.update_or_create(
                api_id=api_id_str,
                defaults={
                    'name': league_name,
                    'sport_key': 'soccer',
                    'sport_group_name': 'Football',
                    'short_name': league_name,
                    'country_name': country_name,
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
        logger.info(f"TASK END: fetch_and_update_leagues_v3_task - SUCCESS")
        logger.info(f"Returning {len(processed_league_ids)} league IDs to next task")
        logger.info("="*80)
        return processed_league_ids
        
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error during league update: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error during league update: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)


@shared_task(name="football_data_app._prepare_and_launch_event_odds_chord_v3", queue='cpu_heavy')
def _prepare_and_launch_event_odds_chord_v3(league_ids: List[int]):
    """
    Intermediate task: Receives league_ids and launches event fetching chord.
    """
    logger.info("="*80)
    logger.info("TASK START: _prepare_and_launch_event_odds_chord_v3")
    logger.info("="*80)
    
    if not league_ids:
        logger.warning("="*80)
        logger.warning("No league IDs received from previous task. Skipping event/odds processing.")
        logger.warning("")
        logger.warning("This usually means:")
        logger.warning("1. No leagues exist in the database yet, OR")
        logger.warning("2. The league fetch from API-Football v3 returned no results")
        logger.warning("")
        logger.warning("FIRST-TIME SETUP: If this is your first run, ensure you have:")
        logger.warning("1. A valid API-Football v3 API key configured")
        logger.warning(f"2. Run: {LEAGUE_SETUP_COMMAND}")
        logger.warning("")
        logger.warning("The fetch_and_update_leagues_v3_task should have populated leagues automatically.")
        logger.warning("Check the logs above for any API errors or authentication issues.")
        logger.warning("="*80)
        logger.info("TASK END: _prepare_and_launch_event_odds_chord_v3 - No leagues to process")
        return
    
    logger.info(f"Received {len(league_ids)} league IDs from previous task: {league_ids}")
    logger.info(f"Preparing to fetch events for {len(league_ids)} leagues...")
    
    try:
        event_fetch_tasks_group = group([
            fetch_events_for_league_v3_task.s(league_id) for league_id in league_ids
        ])
        
        odds_dispatch_callback = dispatch_odds_fetching_after_events_v3_task.s()
        
        logger.info(f"Creating chord with {len(league_ids)} event fetch tasks...")
        task_chord = chord(event_fetch_tasks_group)(odds_dispatch_callback)
        result = task_chord.apply_async()
        
        logger.info(f"Chord dispatched successfully. Chord ID: {result.id if hasattr(result, 'id') else 'N/A'}")
        logger.info(f"Event fetch tasks will execute in parallel for {len(league_ids)} leagues")
        logger.info("After all event fetches complete, odds dispatch task will be triggered")
        logger.info("="*80)
        logger.info("TASK END: _prepare_and_launch_event_odds_chord_v3 - SUCCESS")
        logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Failed to create or dispatch chord: {e}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=600, queue='cpu_heavy')
def fetch_events_for_league_v3_task(self, league_id: int):
    """Fetches and updates events (fixtures) for a single league from API-Football v3."""
    logger.info("="*80)
    logger.info(f"TASK START: fetch_events_for_league_v3_task - League ID: {league_id}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    events_processed_count = 0
    
    try:
        logger.info(f"Fetching league from database (ID: {league_id})...")
        league = League.objects.get(id=league_id)
        logger.info(f"League found: {league.name} (API ID: {league.api_id})")
        
        # Extract the numeric ID from v3_ prefix
        if not league.api_id.startswith('v3_'):
            logger.warning(f"League {league_id} does not have v3_ prefix, skipping")
            return {"league_id": league_id, "status": "skipped", "message": "Not a v3 league"}
        
        api_league_id = int(league.api_id.replace('v3_', ''))
        
        client = APIFootballV3Client()
        
        # Calculate date range for upcoming fixtures
        from_date = datetime.now()
        to_date = from_date + timedelta(days=API_FOOTBALL_V3_LEAD_TIME_DAYS)
        
        # Get current season from Configuration or settings
        current_season = get_current_season()
        
        logger.info(f"Calling APIFootballV3Client.get_fixtures(league_id={api_league_id}, season={current_season}, date_from={from_date.date()}, date_to={to_date.date()})...")
        fixtures_data = client.get_fixtures(
            league_id=api_league_id,
            season=current_season,
            date_from=from_date.strftime('%Y-%m-%d'),
            date_to=to_date.strftime('%Y-%m-%d')
        )
        
        logger.info(f"API returned {len(fixtures_data) if fixtures_data else 0} fixtures for league {league.name}")
        
        fixture_ids_for_odds = []  # Track fixtures that need odds fetching
        
        if fixtures_data:
            logger.info(f"Processing {len(fixtures_data)} fixtures for league {league.name}...")
            with transaction.atomic():
                for idx, fixture_item in enumerate(fixtures_data, 1):
                    fixture_info = fixture_item.get('fixture', {})
                    teams_info = fixture_item.get('teams', {})
                    goals_info = fixture_item.get('goals', {})
                    
                    fixture_id = fixture_info.get('id')
                    fixture_timestamp = fixture_info.get('date')
                    fixture_status = fixture_info.get('status', {}).get('short', '')
                    
                    home_team_data = teams_info.get('home', {})
                    away_team_data = teams_info.get('away', {})
                    
                    home_team_name = home_team_data.get('name')
                    away_team_name = away_team_data.get('name')
                    home_team_id = home_team_data.get('id')
                    away_team_id = away_team_data.get('id')
                    home_team_logo = home_team_data.get('logo')
                    away_team_logo = away_team_data.get('logo')
                    
                    if not fixture_id or not home_team_name or not away_team_name:
                        logger.warning(f"Skipping fixture {idx} - missing required data")
                        continue
                    
                    # Create or get teams
                    home_team, home_created = Team.objects.get_or_create(
                        name=home_team_name,
                        defaults={
                            'api_team_id': f"v3_{home_team_id}" if home_team_id else None,
                            'logo_url': home_team_logo
                        }
                    )
                    if home_created:
                        logger.debug(f"Created new team: {home_team_name}")
                    
                    away_team, away_created = Team.objects.get_or_create(
                        name=away_team_name,
                        defaults={
                            'api_team_id': f"v3_{away_team_id}" if away_team_id else None,
                            'logo_url': away_team_logo
                        }
                    )
                    if away_created:
                        logger.debug(f"Created new team: {away_team_name}")
                    
                    # Parse match datetime
                    match_datetime = parse_api_football_v3_datetime(fixture_timestamp)
                    
                    # Determine fixture status
                    status_map = {
                        'NS': FootballFixture.FixtureStatus.SCHEDULED,  # Not Started
                        'TBD': FootballFixture.FixtureStatus.SCHEDULED,  # Time To Be Defined
                        'LIVE': FootballFixture.FixtureStatus.LIVE,
                        '1H': FootballFixture.FixtureStatus.LIVE,  # First Half
                        'HT': FootballFixture.FixtureStatus.LIVE,  # Halftime
                        '2H': FootballFixture.FixtureStatus.LIVE,  # Second Half
                        'ET': FootballFixture.FixtureStatus.LIVE,  # Extra Time
                        'P': FootballFixture.FixtureStatus.LIVE,  # Penalty
                        'FT': FootballFixture.FixtureStatus.FINISHED,  # Full Time
                        'AET': FootballFixture.FixtureStatus.FINISHED,  # After Extra Time
                        'PEN': FootballFixture.FixtureStatus.FINISHED,  # After Penalty
                        'PST': FootballFixture.FixtureStatus.POSTPONED,
                        'CANC': FootballFixture.FixtureStatus.CANCELLED,
                        'ABD': FootballFixture.FixtureStatus.CANCELLED,  # Abandoned
                    }
                    status = status_map.get(fixture_status, FootballFixture.FixtureStatus.SCHEDULED)
                    
                    # Get scores if available
                    home_score = goals_info.get('home')
                    away_score = goals_info.get('away')
                    
                    # Clean up score values
                    try:
                        home_score = int(home_score) if home_score is not None and home_score != '' else None
                    except (ValueError, TypeError):
                        home_score = None
                    
                    try:
                        away_score = int(away_score) if away_score is not None and away_score != '' else None
                    except (ValueError, TypeError):
                        away_score = None
                    
                    # Create or update fixture
                    fixture_api_id = f"v3_{fixture_id}"
                    fixture, fixture_created = FootballFixture.objects.update_or_create(
                        api_id=fixture_api_id,
                        defaults={
                            'league': league,
                            'home_team': home_team,
                            'away_team': away_team,
                            'match_date': match_datetime,
                            'match_updated': timezone.now(),
                            'status': status,
                            'home_team_score': home_score,
                            'away_team_score': away_score,
                        }
                    )
                    events_processed_count += 1
                    
                    if fixture_created:
                        logger.debug(f"Created fixture: {home_team_name} vs {away_team_name} (Fixture ID: {fixture_id})")
                    else:
                        logger.debug(f"Updated fixture: {home_team_name} vs {away_team_name} (Fixture ID: {fixture_id})")
                    
                    # Add fixture to odds fetching list if it's scheduled and upcoming
                    if status == FootballFixture.FixtureStatus.SCHEDULED and match_datetime:
                        fixture_ids_for_odds.append(fixture.id)
            
            logger.info(f"Successfully processed {events_processed_count} fixtures in database transaction")
            
            # Immediately dispatch odds fetching for scheduled fixtures
            if fixture_ids_for_odds:
                logger.info(f"Dispatching odds fetching tasks for {len(fixture_ids_for_odds)} scheduled fixtures...")
                try:
                    # Create all task signatures
                    odds_tasks = [fetch_odds_for_single_event_v3_task.s(fid) for fid in fixture_ids_for_odds]
                    
                    # Dispatch in batches to avoid overwhelming the queue
                    batch_size = 50
                    for i in range(0, len(odds_tasks), batch_size):
                        batch = odds_tasks[i:i + batch_size]
                        group(batch).apply_async()
                    
                    logger.info(f"Successfully dispatched {len(odds_tasks)} odds fetching tasks in {(len(odds_tasks) + batch_size - 1) // batch_size} batch(es)")
                except Exception as e:
                    logger.error(f"Failed to dispatch odds fetching tasks: {e}", exc_info=True)
                    # Don't fail the entire task if odds dispatching fails
            else:
                logger.info("No scheduled fixtures to fetch odds for")
        
        # Update league's last fetch timestamp
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Updated league.last_fetched_events timestamp for {league.name}")
        
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_v3_task - SUCCESS")
        logger.info(f"League: {league.name}, Events Processed: {events_processed_count}")
        logger.info("="*80)
        return {"league_id": league_id, "status": "success", "events_processed": events_processed_count}
        
    except League.DoesNotExist:
        logger.error(f"TASK ERROR: League with ID {league_id} does not exist in database")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_v3_task - FAILED (League not found)")
        logger.info("="*80)
        return {"league_id": league_id, "status": "error", "message": "League not found"}
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error for league {league_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error fetching events for league {league_id}: {e}", exc_info=True)
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_v3_task - FAILED")
        logger.info("="*80)
        return {"league_id": league_id, "status": "error", "message": str(e)}


@shared_task(bind=True, queue='cpu_heavy')
def dispatch_odds_fetching_after_events_v3_task(self, results_from_event_fetches):
    """
    Step 3: Dispatches individual tasks to fetch odds for each upcoming fixture.
    """
    logger.info("="*80)
    logger.info("TASK START: dispatch_odds_fetching_after_events_v3_task (Odds Dispatch)")
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
    stale_cutoff = now - timedelta(minutes=API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES)
    
    logger.info(f"Querying fixtures that need odds updates...")
    logger.info(f"Criteria: SCHEDULED status, match_date in next {API_FOOTBALL_V3_LEAD_TIME_DAYS} days, odds older than {API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES} minutes")
    
    # Get fixtures that need odds updates (only v3 fixtures)
    # Convert to list once to avoid duplicate queries
    fixture_ids_to_update = list(FootballFixture.objects.filter(
        models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=stale_cutoff),
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=API_FOOTBALL_V3_LEAD_TIME_DAYS)),
        api_id__startswith='v3_'  # Only v3 fixtures
    ).values_list('id', flat=True))
    
    fixture_count = len(fixture_ids_to_update)
    
    # Log more details about what we found
    total_scheduled = FootballFixture.objects.filter(
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=API_FOOTBALL_V3_LEAD_TIME_DAYS)),
        api_id__startswith='v3_'
    ).count()
    logger.info(f"Total scheduled v3 fixtures in date range: {total_scheduled}")
    logger.info(f"Fixtures needing odds update: {fixture_count}")
    
    if not fixture_ids_to_update:
        logger.info("No fixtures require an odds update at this time.")
        logger.info("="*80)
        logger.info("TASK END: dispatch_odds_fetching_after_events_v3_task - No odds updates needed")
        logger.info("="*80)
        return
    
    logger.info(f"Found {fixture_count} fixtures requiring odds updates")
    logger.info(f"Creating {fixture_count} individual odds fetching tasks...")
    
    tasks = [fetch_odds_for_single_event_v3_task.s(fixture_id) for fixture_id in fixture_ids_to_update]
    
    if tasks:
        group(tasks).apply_async()
        logger.info(f"Successfully dispatched {len(tasks)} odds fetching tasks to the queue")
        logger.info("Tasks will fetch odds for each fixture in parallel")
        logger.info("="*80)
        logger.info("TASK END: dispatch_odds_fetching_after_events_v3_task - SUCCESS")
        logger.info(f"Dispatched {len(tasks)} odds fetch tasks")
        logger.info("="*80)


@shared_task(bind=True, max_retries=2, default_retry_delay=300, queue='cpu_heavy')
def fetch_odds_for_single_event_v3_task(self, fixture_id: int):
    """Fetches odds for a single fixture from API-Football v3."""
    # Add jitter to spread out API requests
    jitter_delay = random.uniform(0.5, 3.0)
    logger.debug(f"Applying jitter delay of {jitter_delay:.2f}s before fetching odds for fixture {fixture_id}")
    time.sleep(jitter_delay)
    
    logger.info(f"TASK START: fetch_odds_for_single_event_v3_task - Fixture ID: {fixture_id}")
    
    try:
        logger.debug(f"Fetching fixture {fixture_id} from database...")
        fixture = FootballFixture.objects.select_related('league', 'home_team', 'away_team').get(id=fixture_id)
        logger.info(f"Fetching odds for: {fixture.home_team.name} vs {fixture.away_team.name} (API ID: {fixture.api_id})")
        
        # Extract numeric fixture ID from v3_ prefix
        if not fixture.api_id or not fixture.api_id.startswith('v3_'):
            logger.warning(f"Fixture {fixture_id} is not a v3 fixture, skipping")
            return {"fixture_id": fixture_id, "status": "skipped"}
        
        api_fixture_id = int(fixture.api_id.replace('v3_', ''))
        
        client = APIFootballV3Client()
        
        # Fetch odds for all supported bet types
        logger.info(f"Fetching odds for fixture {api_fixture_id} across {len(API_FOOTBALL_BET_IDS)} bet types...")
        all_odds_data = []
        
        for bet_id in API_FOOTBALL_BET_IDS:
            try:
                logger.debug(f"Fetching bet type {bet_id} for fixture {api_fixture_id}...")
                bet_odds = client.get_odds(fixture_id=api_fixture_id, bet_id=bet_id)
                
                if bet_odds:
                    logger.info(f"  ✓ Bet type {bet_id}: {len(bet_odds)} odds items returned")
                    all_odds_data.extend(bet_odds)
                else:
                    logger.debug(f"  - Bet type {bet_id}: No odds available")
            except Exception as e:
                logger.warning(f"  ✗ Bet type {bet_id}: Error fetching odds - {str(e)}")
        
        logger.info(f"API returned {len(all_odds_data)} total odds items across all bet types for fixture {fixture.id}")
        
        if not all_odds_data:
            logger.info(f"No odds data returned from API for fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name})")
            fixture.last_odds_update = timezone.now()
            fixture.save(update_fields=['last_odds_update'])
            logger.info(f"TASK END: fetch_odds_for_single_event_v3_task - No odds available")
            return {"fixture_id": fixture.id, "status": "no_odds_data"}
        
        logger.info(f"Processing odds data for fixture {fixture.id}...")
        with transaction.atomic():
            fixture_for_update = FootballFixture.objects.select_for_update().get(id=fixture.id)
            
            # Process odds data
            _process_api_football_v3_odds_data(fixture_for_update, all_odds_data)
            
            fixture_for_update.last_odds_update = timezone.now()
            fixture_for_update.save(update_fields=['last_odds_update'])
            
            logger.info(f"Successfully processed and saved odds for fixture {fixture.id}")
            logger.info(f"TASK END: fetch_odds_for_single_event_v3_task - SUCCESS (Fixture: {fixture.id})")
            return {"fixture_id": fixture.id, "status": "success"}
    
    except FootballFixture.DoesNotExist:
        logger.error(f"TASK ERROR: Fixture with ID {fixture_id} not found in database")
        logger.info(f"TASK END: fetch_odds_for_single_event_v3_task - FAILED (Fixture not found)")
        return {"fixture_id": fixture_id, "status": "error", "message": "Fixture not found"}
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error for fixture {fixture_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error for fixture {fixture_id}: {e}", exc_info=True)
        raise self.retry(exc=e)


# --- PIPELINE 2: Score Fetching and Settlement ---

@shared_task(name="football_data_app.run_score_and_settlement_v3_task", queue='cpu_heavy')
def run_score_and_settlement_v3_task():
    """Entry point for fetching scores and updating statuses using API-Football v3."""
    logger.info("="*80)
    logger.info("TASK START: run_score_and_settlement_v3_task (Score & Settlement Pipeline)")
    logger.info("="*80)
    
    try:
        logger.info("Fetching active v3 leagues from database...")
        active_leagues = League.objects.filter(active=True, api_id__startswith='v3_').values_list('id', flat=True)
        league_count = len(active_leagues)
        
        logger.info(f"Found {league_count} active API-Football v3 leagues")
        
        if not league_count:
            logger.warning("="*80)
            logger.warning("No active API-Football v3 leagues found. Skipping score fetching.")
            logger.warning("")
            logger.warning("FIRST-TIME SETUP REQUIRED:")
            logger.warning("To initialize football leagues, run this command:")
            logger.warning(f"  {LEAGUE_SETUP_COMMAND_DOCKER}")
            logger.warning("")
            logger.warning("Or from within the container:")
            logger.warning(f"  {LEAGUE_SETUP_COMMAND}")
            logger.warning("")
            logger.warning("This fetches available leagues from API-Football v3 and populates the database.")
            logger.warning("Without this, no betting data can be fetched or processed.")
            logger.warning("="*80)
            logger.info("TASK END: run_score_and_settlement_v3_task - No active leagues")
            return
        
        logger.info(f"Creating {league_count} score fetching tasks (one per league)...")
        tasks = [fetch_scores_for_league_v3_task.s(league_id) for league_id in active_leagues]
        
        if tasks:
            group(tasks).apply_async()
            logger.info(f"Successfully dispatched {len(tasks)} score fetching tasks to the queue")
            logger.info("="*80)
            logger.info("TASK END: run_score_and_settlement_v3_task - SUCCESS")
            logger.info(f"Dispatched {len(tasks)} tasks")
            logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Failed to dispatch score fetching tasks: {e}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=900, queue='cpu_heavy')
def fetch_scores_for_league_v3_task(self, league_id: int):
    """
    Fetches live and finished match scores for a league from API-Football v3.
    """
    logger.info("="*80)
    logger.info(f"TASK START: fetch_scores_for_league_v3_task - League ID: {league_id}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    now = timezone.now()
    assumed_completion_cutoff = now - timedelta(minutes=API_FOOTBALL_V3_ASSUMED_COMPLETION_MINUTES)
    
    try:
        logger.debug(f"Fetching league {league_id} from database...")
        league = League.objects.get(id=league_id)
        logger.info(f"Processing scores for league: {league.name} (API ID: {league.api_id})")
        
        # Extract numeric league ID
        if not league.api_id.startswith('v3_'):
            logger.warning(f"League {league_id} is not a v3 league, skipping")
            return
        
        api_league_id = int(league.api_id.replace('v3_', ''))
        
        # Get fixtures that need score updates (live or recently started)
        logger.debug("Querying fixtures that need score updates...")
        fixtures_to_check_qs = FootballFixture.objects.filter(
            league=league,
            api_id__startswith='v3_'
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
            logger.info("TASK END: fetch_scores_for_league_v3_task - No updates needed")
            logger.info("="*80)
            return
        
        client = APIFootballV3Client()
        
        logger.info(f"Calling APIFootballV3Client.get_live_fixtures()...")
        live_fixtures = client.get_live_fixtures()
        logger.info(f"Received {len(live_fixtures) if live_fixtures else 0} live fixtures from API")
        
        # Get current season from Configuration or settings
        current_season = get_current_season()
        
        # Get finished matches from the past few days
        date_from = (now - timedelta(days=2)).strftime('%Y-%m-%d')
        date_to = now.strftime('%Y-%m-%d')
        logger.info(f"Calling APIFootballV3Client.get_fixtures(league_id={api_league_id}, season={current_season}, date_from={date_from}, date_to={date_to}, status=FT)...")
        finished_fixtures = client.get_fixtures(
            league_id=api_league_id,
            season=current_season,
            date_from=date_from,
            date_to=date_to,
            status='FT'  # Full Time
        )
        logger.info(f"Received {len(finished_fixtures) if finished_fixtures else 0} finished fixtures from API")
        
        # Combine live and finished fixtures
        all_fixtures = []
        if live_fixtures:
            all_fixtures.extend(live_fixtures)
        if finished_fixtures:
            all_fixtures.extend(finished_fixtures)
        
        # Filter to only fixtures from this league
        league_fixtures = [f for f in all_fixtures if f.get('league', {}).get('id') == api_league_id]
        logger.info(f"Total fixtures for this league after filtering: {len(league_fixtures)}")
        
        processed_api_ids = set()
        fixtures_updated = 0
        fixtures_finished = 0
        fixtures_live = 0
        
        if league_fixtures:
            logger.info(f"Processing {len(league_fixtures)} fixture updates...")
            for idx, fixture_data in enumerate(league_fixtures, 1):
                fixture_info = fixture_data.get('fixture', {})
                goals_info = fixture_data.get('goals', {})
                
                api_fixture_id = fixture_info.get('id')
                if not api_fixture_id:
                    logger.warning(f"Fixture item {idx} missing ID, skipping")
                    continue
                
                fixture_api_id_str = f"v3_{api_fixture_id}"
                processed_api_ids.add(fixture_api_id_str)
                
                try:
                    with transaction.atomic():
                        fixture = FootballFixture.objects.select_for_update().get(api_id=fixture_api_id_str)
                        
                        if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                            logger.debug(f"Fixture {fixture.id} already FINISHED, skipping")
                            continue
                        
                        # Get scores
                        home_score = goals_info.get('home')
                        away_score = goals_info.get('away')
                        fixture_status = fixture_info.get('status', {}).get('short', '')
                        
                        # Parse scores
                        try:
                            home_score = int(home_score) if home_score is not None and home_score != '' else None
                        except (ValueError, TypeError):
                            home_score = None
                        
                        try:
                            away_score = int(away_score) if away_score is not None and away_score != '' else None
                        except (ValueError, TypeError):
                            away_score = None
                        
                        # Update scores if available
                        if home_score is not None:
                            fixture.home_team_score = home_score
                        if away_score is not None:
                            fixture.away_team_score = away_score
                        
                        fixture.last_score_update = timezone.now()
                        fixture.match_updated = timezone.now()
                        
                        update_fields = ['home_team_score', 'away_team_score', 'status', 'last_score_update', 'match_updated']
                        
                        # Update status
                        if fixture_status in ['FT', 'AET', 'PEN']:  # Finished statuses
                            fixture.status = FootballFixture.FixtureStatus.FINISHED
                            fixture.save(update_fields=update_fields)
                            fixtures_finished += 1
                            logger.info(f"Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) marked FINISHED. Score: {home_score}-{away_score}")
                            
                            # Import settlement tasks from legacy tasks (reusable)
                            from .tasks_apifootball import settle_fixture_pipeline_task
                            logger.info(f"Triggering settlement pipeline for fixture {fixture.id}...")
                            settle_fixture_pipeline_task.delay(fixture.id)
                        elif fixture_status in ['LIVE', '1H', 'HT', '2H', 'ET', 'P']:  # Live statuses
                            fixture.status = FootballFixture.FixtureStatus.LIVE
                            fixture.save(update_fields=update_fields)
                            fixtures_live += 1
                            logger.debug(f"Fixture {fixture.id} is LIVE. Score: {home_score}-{away_score}")
                        else:
                            fixture.save(update_fields=update_fields)
                        
                        fixtures_updated += 1
                
                except FootballFixture.DoesNotExist:
                    logger.warning(f"Received score data for unknown fixture API ID: {fixture_api_id_str}")
        
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
                        
                        from .tasks_apifootball import settle_fixture_pipeline_task
                        settle_fixture_pipeline_task.delay(fixture.id)
            
            if fixtures_assumed_finished > 0:
                logger.info(f"Marked {fixtures_assumed_finished} fixtures as assumed finished")
        
        logger.info("="*80)
        logger.info(f"TASK END: fetch_scores_for_league_v3_task - SUCCESS")
        logger.info(f"League: {league.name}, Updated: {fixtures_updated}, Finished: {fixtures_finished}, Live: {fixtures_live}")
        logger.info("="*80)
    
    except League.DoesNotExist:
        logger.error(f"TASK ERROR: League {league_id} not found in database")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_scores_for_league_v3_task - FAILED (League not found)")
        logger.info("="*80)
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error for league {league_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error fetching scores for league {league_id}: {e}", exc_info=True)
        raise self.retry(exc=e)


# --- Task Aliases for Backward Compatibility ---

@shared_task(name="football_data_app.run_api_football_v3_full_update_alias", queue='cpu_heavy')
def run_api_football_v3_full_update():
    """
    Alias for run_api_football_v3_full_update_task with a simplified name.
    """
    return run_api_football_v3_full_update_task()


@shared_task(name="football_data_app.run_score_and_settlement_v3_alias", queue='cpu_heavy')
def run_score_and_settlement_v3():
    """
    Alias for run_score_and_settlement_v3_task with a simplified name.
    """
    return run_score_and_settlement_v3_task()
