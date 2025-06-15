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
EVENT_RETRY_DELAY = getattr(settings, 'THE_ODDS_API_EVENT_RETRY_DELAY', 300)

# --- Helper Functions ---
def _parse_outcome_details(outcome_name: str, market_key: str) -> tuple:
    """Enhanced outcome parser with better error handling"""
    name_part, point_part = outcome_name, None
    if market_key in ['totals', 'spreads', 'alternate_totals']:
        try:
            parts = outcome_name.split()
            last_part = parts[-1]
            if last_part.replace('.', '', 1).lstrip('+-').isdigit():
                point_part = float(last_part)
                name_part = " ".join(parts[:-1]) or outcome_name
        except (ValueError, IndexError) as e:
            logger.debug(f"Couldn't parse point from {outcome_name} for {market_key}: {str(e)}")
    return name_part, point_part

def _get_active_fixtures(league: League) -> List[str]:
    """Get event IDs needing updates with staleness check"""
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)
    
    return list(FootballFixture.objects.filter(
        league=league,
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
    ).filter(
        models.Q(last_odds_update__isnull=True) |
        models.Q(last_odds_update__lt=stale_cutoff)
    ).values_list('api_id', flat=True)[:200])  # Limit for safety

def _process_bookmaker_data(fixture: FootballFixture, bookmaker_data: dict, market_types: List[str]):
    """Process and save bookmaker data with atomic transactions"""
    try:
        bookmaker, _ = Bookmaker.objects.get_or_create(
            api_bookmaker_key=bookmaker_data['key'],
            defaults={'name': bookmaker_data['title']}
        )
        
        for market_data in bookmaker_data.get('markets', []):
            market_key = market_data['key']
            if market_key not in market_types:
                continue
                
            # Delete existing markets before creating new ones
            Market.objects.filter(
                fixture_display=fixture,
                bookmaker=bookmaker,
                api_market_key=market_key
            ).delete()
            
            category, _ = MarketCategory.objects.get_or_create(
                name=market_key.replace("_", " ").title()
            )
            
            market = Market.objects.create(
                fixture_display=fixture,
                bookmaker=bookmaker,
                category=category,
                api_market_key=market_key,
                last_updated_odds_api=parser.isoparse(market_data['last_update'])
            )
            
            for outcome_data in market_data.get('outcomes', []):
                name, point = _parse_outcome_details(outcome_data['name'], market_key)
                MarketOutcome.objects.create(
                    market=market,
                    outcome_name=name,
                    odds=Decimal(str(outcome_data['price'])),  # Ensure Decimal conversion
                    point_value=point
                )
    except Exception as e:
        logger.error(f"Error processing bookmaker data: {str(e)}")
        raise

# --- Core Tasks ---
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """Fetch and update all leagues from API"""
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
        logger.exception(f"Task {self.request.id}: Critical error in league fetching")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id):
    """Fetch events for a specific league"""
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
                        'match_date': parser.isoparse(item['commence_time']),
                        'status': FootballFixture.FixtureStatus.SCHEDULED
                    }
                )
        
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
    except Exception as e:
        logger.exception(f"Task {self.request.id}: Error fetching events for league {league_id}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def process_leagues_and_dispatch_subtasks_task(self, previous_task_result=None):
    """Orchestrate league processing and task dispatching"""
    now = timezone.now()
    leagues = League.objects.filter(active=True)
    
    for league in leagues:
        # Update events if stale
        if not league.last_fetched_events or league.last_fetched_events < (now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)):
            fetch_events_for_league_task.apply_async(args=[league.id])

        # Process odds updates
        event_ids = _get_active_fixtures(league)
        
        if event_ids:
            # Dispatch batch tasks for main markets
            if DEFAULT_ODDS_API_MARKETS:
                for i in range(0, len(event_ids), ODDS_FETCH_EVENT_BATCH_SIZE):
                    fetch_odds_for_event_batch_task.apply_async(
                        args=[league.id, event_ids[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]]
                    )
            
            # Dispatch individual tasks for additional markets
            if ADDITIONAL_ODDS_API_MARKETS:
                for event_id in event_ids:
                    fetch_additional_markets_task.apply_async(args=[event_id])

@shared_task(bind=True, max_retries=MAX_EVENT_RETRIES, default_retry_delay=EVENT_RETRY_DELAY)
def fetch_additional_markets_task(self, event_id):
    """Fetch additional markets for single event"""
    client = TheOddsAPIClient()
    try:
        fixture = FootballFixture.objects.get(api_id=event_id)
        odds_data = client.get_event_odds(
            event_id=event_id,
            regions=DEFAULT_ODDS_API_REGIONS,
            markets=ADDITIONAL_ODDS_API_MARKETS,
            bookmakers=TARGET_BOOKMAKER
        )
        
        if not odds_data:
            logger.warning(f"No additional markets data for event {event_id}")
            return
            
        with transaction.atomic():
            for bookmaker_data in odds_data.get('bookmakers', []):
                _process_bookmaker_data(fixture, bookmaker_data, ADDITIONAL_ODDS_API_MARKETS.split(','))
            
            fixture.last_odds_update = timezone.now()
            fixture.save(update_fields=['last_odds_update'])
            
    except FootballFixture.DoesNotExist:
        logger.warning(f"Fixture {event_id} no longer exists")
    except TheOddsAPIException as e:
        if e.status_code in [404, 422]:
            logger.warning(f"API error {e.status_code} for event {event_id}")
        else:
            logger.error(f"API error for event {event_id}: {str(e)}")
            raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Error processing event {event_id}")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, league_id, event_ids, markets=None, regions=None):
    """Fetch odds for batch of events"""
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
            logger.info(f"No odds data for batch of {len(event_ids)} events")
            return
            
        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}
        
        with transaction.atomic():
            for event_data in odds_data:
                fixture = fixtures_map.get(event_data['id'])
                if not fixture:
                    continue
                    
                # Process each bookmaker's markets
                for bookmaker_data in event_data.get('bookmakers', []):
                    _process_bookmaker_data(fixture, bookmaker_data, markets_to_fetch.split(','))
                
                fixture.last_odds_update = timezone.now()
                fixture.save(update_fields=['last_odds_update'])
                
    except Exception as e:
        logger.exception(f"Error processing batch of {len(event_ids)} events")
        raise self.retry(exc=e)

# --- Score Update Tasks ---
@shared_task(name="football_data_app.run_score_update_task")
def run_score_update_task():
    """Entry point for score updates"""
    for league in League.objects.filter(active=True):
        fetch_scores_for_league_task.apply_async(args=[league.id])

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id):
    """Fetch and process scores for a league"""
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
                    if fixture.status == FootballFixture.FixtureStatus.SCHEDULED and commence_time <= now:
                        fixture.status = FootballFixture.FixtureStatus.LIVE
                        fixture.save()
                        
    except Exception as e:
        logger.exception(f"Error fetching scores for league {league_id}")
        raise self.retry(exc=e)

# --- Settlement Tasks ---
@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id):
    """Determine outcome statuses for finished fixture"""
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
        logger.exception(f"Error settling outcomes for fixture {fixture_id}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id):
    """Update bet statuses based on settled outcomes"""
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
        logger.exception(f"Error settling bets for fixture {fixture_id}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id):
    """Settle all betting tickets for a fixture"""
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
        logger.exception(f"Error settling tickets for fixture {fixture_id}")
        raise self.retry(exc=e)

# --- Maintenance Tasks ---
@shared_task
def cleanup_old_data(days_old: int = 30):
    """Cleanup old data to maintain performance"""
    cutoff = timezone.now() - timedelta(days=days_old)
    
    with transaction.atomic():
        old_fixtures = FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.FINISHED,
            match_date__lt=cutoff
        )
        count = old_fixtures.count()
        old_fixtures.delete()
        logger.info(f"Deleted {count} old fixtures")

@shared_task
def verify_data_consistency():
    """Check for data consistency issues"""
    issues = []
    
    # Check for fixtures without markets
    no_markets = FootballFixture.objects.filter(
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__gt=timezone.now(),
        markets__isnull=True
    ).count()
    
    if no_markets > 0:
        issues.append(f"{no_markets} upcoming fixtures have no markets")
    
    # Check for markets without outcomes
    no_outcomes = Market.objects.filter(outcomes__isnull=True).count()
    if no_outcomes > 0:
        issues.append(f"{no_outcomes} markets have no outcomes")
    
    if issues:
        logger.warning("Data consistency issues found:\n" + "\n".join(issues))
        return issues
    
    logger.info("Data consistency check passed")
    return []

# --- Main Entry Point ---
@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """Main entry point for full system update"""
    pipeline = chain(
        fetch_and_update_leagues_task.s(),
        process_leagues_and_dispatch_subtasks_task.s()
    )
    pipeline.apply_async()