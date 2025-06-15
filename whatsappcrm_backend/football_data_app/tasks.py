# football_data_app/tasks.py
import logging
from django.conf import settings
from celery import shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# --- Configuration ---
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us,au")
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals")
ADDITIONAL_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_ADDITIONAL_MARKETS', "btts,alternate_totals,h2h_3way")
TARGET_BOOKMAKER = getattr(settings, 'THE_ODDS_API_TARGET_BOOKMAKER', None)
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
ASSUMED_COMPLETION_MINUTES = getattr(settings, 'THE_ODDS_API_ASSUMED_COMPLETION_MINUTES', 120)
MAX_EVENT_RETRIES = getattr(settings, 'THE_ODDS_API_MAX_EVENT_RETRIES', 3)
EVENT_RETRY_DELAY = getattr(settings, 'THE_ODDS_API_EVENT_RETRY_DELAY', 300)  # seconds

# --- Helper Functions ---
def _parse_outcome_details(outcome_name_api: str, market_key_api: str) -> tuple:
    """Parse outcome details from API response."""
    name_part, point_part = outcome_name_api, None
    if market_key_api in ['totals', 'spreads', 'alternate_totals']:
        try:
            parts = outcome_name_api.split()
            last_part = parts[-1]
            if last_part.replace('.', '', 1).lstrip('+-').isdigit():
                point_part = float(last_part)
                name_part = " ".join(parts[:-1]) or outcome_name_api
        except (ValueError, IndexError):
            logger.debug(f"Could not parse point from outcome: '{outcome_name_api}' for market '{market_key_api}'")
    return name_part, point_part

def _get_fixtures_needing_odds(league: League) -> List[str]:
    """Get event IDs for fixtures needing odds updates."""
    now = timezone.now()
    return list(FootballFixture.objects.filter(
        league=league,
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
    .filter(
        models.Q(last_odds_update__isnull=True) | 
        models.Q(last_odds_update__lt=now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES))
    .values_list('api_id', flat=True))

# --- Data Fetching & Processing Tasks ---
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """Fetch and update all soccer leagues from The Odds API."""
    client = TheOddsAPIClient()
    try:
        sports_data = client.get_sports(all_sports=True)
        for item in sports_data:
            if 'soccer' not in item.get('key', ''):
                continue
                
            League.objects.update_or_create(
                api_id=item['key'],
                defaults={
                    'name': item.get('title', 'Unknown'), 
                    'sport_key': 'soccer', 
                    'active': True
                }
            )
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Critical error in league fetching. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id: int):
    """Fetch events for a specific league."""
    client = TheOddsAPIClient()
    try:
        league = League.objects.get(id=league_id)
        events_data = client.get_events(sport_key=league.api_id)
        
        for item in events_data:
            if not item.get('home_team') or not item.get('away_team'):
                continue
                
            with transaction.atomic():
                home_obj, _ = Team.objects.get_or_create(name=item['home_team'])
                away_obj, _ = Team.objects.get_or_create(name=item['away_team'])
                
                FootballFixture.objects.update_or_create(
                    api_id=item['id'],
                    defaults={
                        'league': league,
                        'home_team': home_obj,
                        'away_team': away_obj,
                        'match_date': parser.isoparse(item['commence_time'])
                    }
                )
        
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Error fetching events for league {league_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def process_leagues_and_dispatch_subtasks_task(self, previous_task_result=None):
    """Process all leagues and dispatch appropriate subtasks."""
    now = timezone.now()
    leagues = League.objects.filter(active=True)
    
    # Create groups of tasks for each league
    tasks = []
    for league in leagues:
        # Check if we need to fetch events
        if not league.last_fetched_events or league.last_fetched_events < (now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)):
            tasks.append(fetch_events_for_league_task.si(league.id))
        
        # Check for fixtures needing odds
        event_ids = _get_fixtures_needing_odds(league)
        if event_ids:
            if DEFAULT_ODDS_API_MARKETS:
                # Batch process odds fetching
                batch_tasks = [
                    fetch_odds_for_event_batch_task.si(league.id, event_ids[i:i + ODDS_FETCH_EVENT_BATCH_SIZE])
                    for i in range(0, len(event_ids), ODDS_FETCH_EVENT_BATCH_SIZE)
                ]
                tasks.extend(batch_tasks)
            
            if ADDITIONAL_ODDS_API_MARKETS:
                # Process additional markets in parallel
                additional_tasks = [
                    fetch_additional_markets_task.si(event_id)
                    for event_id in event_ids
                ]
                tasks.extend(additional_tasks)
    
    # Execute all tasks in parallel
    if tasks:
        group(tasks).apply_async()

@shared_task(bind=True, max_retries=MAX_EVENT_RETRIES, default_retry_delay=EVENT_RETRY_DELAY)
def fetch_additional_markets_task(self, event_id: str):
    """Fetch additional markets for a specific event."""
    client = TheOddsAPIClient()
    try:
        fixture = FootballFixture.objects.get(api_id=event_id)
        event_odds_data = client.get_event_odds(
            event_id, 
            DEFAULT_ODDS_API_REGIONS, 
            ADDITIONAL_ODDS_API_MARKETS, 
            bookmakers=TARGET_BOOKMAKER
        )
        
        if not event_odds_data:
            logger.warning(f"No additional markets data for event {event_id}")
            return
            
        with transaction.atomic():
            for bookmaker_data in event_odds_data.get('bookmakers', []):
                bookmaker, _ = Bookmaker.objects.get_or_create(
                    api_bookmaker_key=bookmaker_data['key'],
                    defaults={'name': bookmaker_data['title']}
                )
                
                for market_data in bookmaker_data.get('markets', []):
                    market_key = market_data['key']
                    # Delete existing markets before creating new ones
                    Market.objects.filter(
                        fixture_display=fixture,
                        bookmaker=bookmaker,
                        api_market_key=market_key
                    ).delete()
                    
                    category, _ = MarketCategory.objects.get_or_create(
                        name=market_key.replace("_", " ").title()
                    )
                    
                    market_instance = Market.objects.create(
                        fixture_display=fixture,
                        bookmaker=bookmaker,
                        category=category,
                        api_market_key=market_key,
                        last_updated_odds_api=parser.isoparse(market_data['last_update'])
                    )
                    
                    for outcome_data in market_data.get('outcomes', []):
                        name, point = _parse_outcome_details(outcome_data['name'], market_key)
                        MarketOutcome.objects.create(
                            market=market_instance,
                            outcome_name=name,
                            odds=outcome_data['price'],
                            point_value=point
                        )
                        
            fixture.last_odds_update = timezone.now()
            fixture.save(update_fields=['last_odds_update'])
            
    except TheOddsAPIException as e:
        if e.status_code in [404, 422]:
            logger.warning(f"Task {self.request.id}: API error {e.status_code} for event {event_id}. Won't retry.")
        else:
            logger.warning(f"Task {self.request.id}: API error for event {event_id}. Retrying...")
            raise self.retry(exc=e)
    except FootballFixture.DoesNotExist:
        logger.warning(f"Fixture with api_id {event_id} does not exist. Won't retry.")
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Unexpected error for event {event_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, league_id: int, event_ids: List[str], markets: Optional[str] = None, regions: Optional[str] = None):
    """Fetch odds for a batch of events."""
    client = TheOddsAPIClient()
    markets_to_fetch = markets or DEFAULT_ODDS_API_MARKETS
    
    try:
        league = League.objects.get(id=league_id)
        odds_data = client.get_odds(
            league.api_id,
            regions or DEFAULT_ODDS_API_REGIONS,
            markets_to_fetch,
            event_ids,
            bookmakers=TARGET_BOOKMAKER
        )
        
        if not odds_data:
            logger.info(f"No odds data returned for batch of {len(event_ids)} events")
            return
            
        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}
        
        with transaction.atomic():
            for event_data in odds_data:
                fixture = fixtures_map.get(event_data['id'])
                if not fixture:
                    continue
                    
                # Delete existing markets before creating new ones
                Market.objects.filter(
                    fixture_display=fixture,
                    api_market_key__in=markets_to_fetch.split(',')
                ).delete()
                
                for bookmaker_data in event_data.get('bookmakers', []):
                    bookmaker, _ = Bookmaker.objects.get_or_create(
                        api_bookmaker_key=bookmaker_data['key'],
                        defaults={'name': bookmaker_data['title']}
                    )
                    
                    for market_data in bookmaker_data.get('markets', []):
                        market_key = market_data['key']
                        category, _ = MarketCategory.objects.get_or_create(
                            name=market_key.replace("_", " ").title()
                        )
                        
                        market_instance = Market.objects.create(
                            fixture_display=fixture,
                            bookmaker=bookmaker,
                            category=category,
                            api_market_key=market_key,
                            last_updated_odds_api=parser.isoparse(market_data['last_update'])
                        )
                        
                        for outcome_data in market_data.get('outcomes', []):
                            name, point = _parse_outcome_details(outcome_data['name'], market_key)
                            MarketOutcome.objects.create(
                                market=market_instance,
                                outcome_name=name,
                                odds=outcome_data['price'],
                                point_value=point
                            )
                
                fixture.last_odds_update = timezone.now()
                fixture.save(update_fields=['last_odds_update'])
                
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Error fetching odds for batch. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id: int):
    """Fetch scores for a league and update fixture statuses."""
    now = timezone.now()
    try:
        league = League.objects.get(id=league_id)
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(league=league, status=FootballFixture.FixtureStatus.SCHEDULED, 
                    match_date__lt=now + timedelta(minutes=5))
        ).distinct()
        
        if not fixtures_to_check.exists():
            return
            
        event_ids_to_fetch = list(fixtures_to_check.values_list('api_id', flat=True))
        if not event_ids_to_fetch:
            return

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=event_ids_to_fetch)
        
        for score_item in scores_data:
            fixture = FootballFixture.objects.filter(api_id=score_item['id']).first()
            if not fixture:
                continue
                
            with transaction.atomic():
                commence_time = parser.isoparse(score_item['commence_time'])
                if timezone.is_naive(commence_time):
                    commence_time = timezone.make_aware(commence_time, timezone.get_current_timezone())
                
                is_completed = score_item.get('completed', False) or (
                    now - commence_time > timedelta(minutes=ASSUMED_COMPLETION_MINUTES))
                
                if is_completed:
                    if fixture.status != FootballFixture.FixtureStatus.FINISHED:
                        home_s, away_s = None, None
                        if score_item.get('scores'):
                            for score in score_item['scores']:
                                if score['name'] == fixture.home_team.name:
                                    home_s = score['score']
                                elif score['name'] == fixture.away_team.name:
                                    away_s = score['score']
                        
                        fixture.home_team_score = int(home_s) if home_s else None
                        fixture.away_team_score = int(away_s) if away_s else None
                        fixture.status = FootballFixture.FixtureStatus.FINISHED
                        fixture.save()
                        
                        # Chain settlement tasks
                        chain(
                            settle_outcomes_for_fixture_task.s(fixture.id),
                            settle_bets_for_fixture_task.s(),
                            settle_tickets_for_fixture_task.s()
                        ).apply_async()
                else:
                    if (fixture.status == FootballFixture.FixtureStatus.SCHEDULED and 
                        commence_time <= now):
                        fixture.status = FootballFixture.FixtureStatus.LIVE
                        fixture.save()
                        
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Error fetching scores for league {league_id}.")
        raise self.retry(exc=e)

# Settlement tasks (unchanged but included for completeness)
@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id: int):
    """Determine outcome statuses for a finished fixture."""
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, status=FootballFixture.FixtureStatus.FINISHED)
        if fixture.home_team_score is None or fixture.away_team_score is None:
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
                elif market.api_market_key in ['totals', 'alternate_totals'] and outcome.point_value is not None:
                    total_score = home_score + away_score
                    if 'over' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score > outcome.point_value else 'PUSH' if total_score == outcome.point_value else 'LOST'
                    elif 'under' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score < outcome.point_value else 'PUSH' if total_score == outcome.point_value else 'LOST'
                elif market.api_market_key == 'btts':
                    if ((outcome.outcome_name == 'Yes' and home_score > 0 and away_score > 0) or
                       (outcome.outcome_name == 'No' and not (home_score > 0 and away_score > 0))):
                        new_status = 'WON'
                
                if new_status != 'PENDING':
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)
        
        if outcomes_to_update:
            MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
            
        return fixture_id
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Error settling outcomes for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id: int):
    """Update bet statuses based on settled outcomes."""
    if not fixture_id:
        return
        
    try:
        bets = Bet.objects.filter(
            market_outcome__market__fixture_display_id=fixture_id,
            status='PENDING'
        ).select_related('market_outcome')
        
        for bet in bets:
            if bet.market_outcome.result_status != 'PENDING':
                bet.status = bet.market_outcome.result_status
                bet.save()
                
        return fixture_id
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Error settling bets for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id: int):
    """Settle all betting tickets containing bets for this fixture."""
    if not fixture_id:
        return
        
    try:
        ticket_ids = BetTicket.objects.filter(
            bets__market_outcome__market__fixture_display_id=fixture_id
        ).distinct().values_list('id', flat=True)
        
        for ticket_id in ticket_ids:
            ticket = BetTicket.objects.prefetch_related('bets').get(id=ticket_id)
            if ticket.status == 'PENDING' and all(b.status != 'PENDING' for b in ticket.bets.all()):
                ticket.settle_ticket()
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Error settling tickets for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """Main task to run full update pipeline."""
    pipeline = chain(
        fetch_and_update_leagues_task.s(),
        process_leagues_and_dispatch_subtasks_task.s()
    )
    pipeline.apply_async()

@shared_task(name="football_data_app.run_score_update_task")
def run_score_update_task():
    """Task to update scores for all active leagues."""
    for league in League.objects.filter(active=True):
        fetch_scores_for_league_task.apply_async(args=[league.id])