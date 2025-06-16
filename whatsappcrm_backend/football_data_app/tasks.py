import logging
from django.conf import settings
from celery import shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta
from decimal import Decimal
from typing import List

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# --- Configuration ---
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us,au")
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals")
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
ASSUMED_COMPLETION_MINUTES = getattr(settings, 'THE_ODDS_API_ASSUMED_COMPLETION_MINUTES', 120)
MAX_EVENT_RETRIES = getattr(settings, 'THE_ODDS_API_MAX_EVENT_RETRIES', 3)
EVENT_RETRY_DELAY = getattr(settings, 'THE_ODDS_API_EVENT_RETRY_DELAY', 300)
ODDS_UPCOMING_STALENESS_MINUTES =  15
TARGET_BOOKMAKER ='unibet'
# --- Helper Functions ---
@transaction.atomic
def _process_bookmaker_data(fixture: FootballFixture, bookmaker_data: dict, market_keys: List[str]):
    """Processes and saves market and outcome data for a given fixture and bookmaker."""
    bookmaker, _ = Bookmaker.objects.get_or_create(
        api_bookmaker_key=bookmaker_data['key'],
        defaults={'name': bookmaker_data['title']}
    )
    
    for market_data in bookmaker_data.get('markets', []):
        market_key = market_data['key']
        if market_key not in market_keys:
            continue
            
        category, _ = MarketCategory.objects.get_or_create(name=market_key.replace("_", " ").title())
        
        market, created = Market.objects.update_or_create(
            fixture_display=fixture,
            bookmaker=bookmaker,
            api_market_key=market_key,
            category=category,
            defaults={'last_updated_odds_api': parser.isoparse(market_data['last_update'])}
        )
        
        if not created:
            market.outcomes.all().delete()
            
        outcomes_to_create = [
            MarketOutcome(market=market, outcome_name=o['name'], odds=Decimal(str(o['price'])))
            for o in market_data.get('outcomes', [])
        ]
        MarketOutcome.objects.bulk_create(outcomes_to_create)

# --- Core Data Fetching Tasks ---
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """Step 1: Fetches all available soccer leagues from the API."""
    logger.info("Starting league update task.")
    client = TheOddsAPIClient()
    try:
        sports_data = client.get_sports(all_sports=True)
        active_leagues = []
        for item in sports_data:
            if 'soccer' in item.get('group', ''):
                league, _ = League.objects.update_or_create(
                    api_id=item['key'],
                    defaults={'name': item.get('title'), 'sport_key': item.get('group'), 'active': True}
                )
                active_leagues.append(league.id)
        logger.info(f"Successfully updated {len(active_leagues)} leagues.")
        return active_leagues
    except TheOddsAPIException as e:
        logger.exception(f"API error during league update: {e}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def dispatch_event_fetching_task(self, league_ids: List[int]):
    """Step 2: Dispatches parallel tasks to fetch events for each active league."""
    if not league_ids:
        logger.warning("No league IDs provided to dispatch event fetching.")
        return
    logger.info(f"Dispatching event fetching for {len(league_ids)} leagues.")
    event_fetch_group = group(fetch_events_for_league_task.s(league_id) for league_id in league_ids)
    event_fetch_group.apply_async()

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id: int):
    """Fetches and updates events (fixtures) for a single league."""
    logger.info(f"Fetching events for league ID: {league_id}")
    try:
        league = League.objects.get(id=league_id)
        client = TheOddsAPIClient()
        events_data = client.get_events(sport_key=league.api_id)
        
        with transaction.atomic():
            for item in events_data:
                home_team, _ = Team.objects.get_or_create(name=item['home_team'])
                away_team, _ = Team.objects.get_or_create(name=item['away_team'])
                FootballFixture.objects.update_or_create(
                    api_id=item['id'],
                    defaults={
                        'league': league,
                        'home_team': home_team,
                        'away_team': away_team,
                        'match_date': parser.isoparse(item['commence_time']),
                    }
                )
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Successfully fetched events for league ID: {league_id}")
    except League.DoesNotExist:
        logger.error(f"League with ID {league_id} does not exist.")
    except TheOddsAPIException as e:
        logger.exception(f"API error fetching events for league {league_id}: {e}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def dispatch_odds_fetching_task(self, _=None):
    """
    Step 3: Dispatches parallel tasks to fetch odds for upcoming fixtures.
    Accepts an argument from the preceding task in the chain but does not use it.
    """
    logger.info("Dispatching odds fetching tasks.")
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)
    
    fixtures_to_update = FootballFixture.objects.filter(
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
    ).filter(
        models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=stale_cutoff)
    ).values('id', 'league_id', 'api_id', 'league__api_id')

    if not fixtures_to_update:
        logger.info("No fixtures require an odds update at this time.")
        return

    odds_tasks = [
        fetch_odds_for_event_batch_task.s(
            league_id=f['league_id'],
            event_ids=[f['api_id']],
            markets=DEFAULT_ODDS_API_MARKETS,
            regions=DEFAULT_ODDS_API_REGIONS
        ) for f in fixtures_to_update
    ]
    
    group(odds_tasks).apply_async()

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, league_id: int, event_ids: List[str], markets: str, regions: str):
    """Fetches odds for a batch of events."""
    logger.info(f"Fetching odds for {len(event_ids)} events in league {league_id}.")
    try:
        league = League.objects.get(id=league_id)
        client = TheOddsAPIClient()
        odds_data = client.get_odds(league.api_id, regions, markets, event_ids, bookmakers=TARGET_BOOKMAKER)
        
        if not odds_data:
            return

        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}
        for event_data in odds_data:
            if fixture := fixtures_map.get(event_data['id']):
                with transaction.atomic():
                    for bookmaker_data in event_data.get('bookmakers', []):
                        _process_bookmaker_data(fixture, bookmaker_data, markets.split(','))
                    fixture.last_odds_update = timezone.now()
                    fixture.save(update_fields=['last_odds_update'])

    except League.DoesNotExist:
        logger.error(f"League {league_id} not found for odds fetch.")
    except TheOddsAPIException as e:
        logger.exception(f"API error in odds fetch batch: {e}")
        raise self.retry(exc=e)

# --- Score and Settlement Tasks ---

@shared_task(bind=True)
def run_score_update_task(self, _=None):
    """
    Step 4: Dispatches parallel tasks to fetch scores for all active leagues.
    Accepts an argument from the preceding task in the chain but does not use it.
    """
    logger.info("Starting score update process.")
    active_leagues = League.objects.filter(active=True).values_list('id', flat=True)
    score_update_group = group(fetch_scores_for_league_task.s(league_id) for league_id in active_leagues)
    score_update_group.apply_async()

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id: int):
    """Fetches and processes scores for a single league."""
    logger.info(f"Fetching scores for league ID: {league_id}")
    now = timezone.now()
    try:
        league = League.objects.get(id=league_id)
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(league=league, status=FootballFixture.FixtureStatus.SCHEDULED, match_date__lt=now)
        ).values_list('api_id', flat=True)

        if not fixtures_to_check:
            return

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=list(fixtures_to_check))
        
        for score_item in scores_data:
            with transaction.atomic():
                fixture = FootballFixture.objects.select_for_update().get(api_id=score_item['id'])
                if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                    continue

                if score_item.get('completed', False):
                    home_score, away_score = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_score = score['score']
                            elif score['name'] == fixture.away_team.name: away_score = score['score']
                    
                    fixture.home_team_score = int(home_score) if home_score is not None else None
                    fixture.away_team_score = int(away_score) if away_score is not None else None
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    fixture.save()
                    
                    settle_fixture_pipeline_task.delay(fixture.id)
                else:
                    if fixture.status == FootballFixture.FixtureStatus.SCHEDULED and parser.isoparse(score_item['commence_time']) <= now:
                        fixture.status = FootballFixture.FixtureStatus.LIVE
                        fixture.save()

    except League.DoesNotExist:
        logger.error(f"League {league_id} not found for score update.")
    except TheOddsAPIException as e:
        logger.exception(f"API error fetching scores for league {league_id}: {e}")
        raise self.retry(exc=e)

@shared_task(name="football_data_app.settle_fixture_pipeline")
def settle_fixture_pipeline_task(fixture_id: int):
    """Creates a settlement chain (outcomes -> bets -> tickets) for a single finished fixture."""
    pipeline = chain(
        settle_outcomes_for_fixture_task.s(fixture_id),
        settle_bets_for_fixture_task.s(),
        settle_tickets_for_fixture_task.s()
    )
    pipeline.apply_async()

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

# --- Main Orchestration ---
@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """
    Main entry point for the entire data update process.
    Orchestrates fetching leagues, events, odds, and scores in a robust, sequential pipeline.
    """
    pipeline = chain(
        fetch_and_update_leagues_task.s(),
        dispatch_event_fetching_task.s(),
        dispatch_odds_fetching_task.s(),
        run_score_update_task.s()
    )
    pipeline.apply_async()