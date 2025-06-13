# football_data_app/tasks.py
import logging
from django.conf import settings
from celery import shared_task, chain
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta
from decimal import Decimal

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# --- Configuration ---
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us,au")
# Configure markets for the appropriate endpoints
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,outrights")
ADDITIONAL_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_ADDITIONAL_MARKETS', "btts,alternate_totals,h2h_3way")
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
ASSUMED_COMPLETION_MINUTES = getattr(settings, 'THE_ODDS_API_ASSUMED_COMPLETION_MINUTES', 120)


# --- Helper Function ---
def _parse_outcome_details(outcome_name_api, market_key_api):
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

# --- Data Fetching & Processing Tasks ---

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """Step 1: Fetches and updates football leagues from the API."""
    task_id = self.request.id
    logger.info(f"Task {task_id}: Starting league fetch task.")
    client = TheOddsAPIClient()
    created_count, updated_count = 0, 0
    try:
        sports_data = client.get_sports(all_sports=True)
        for item in sports_data:
            if 'soccer' not in item.get('key', ''):
                continue
            _, created = League.objects.update_or_create(
                api_id=item['key'],
                defaults={'name': item.get('title', 'Unknown'), 'sport_key': 'soccer', 'active': True}
            )
            if created: created_count += 1
            else: updated_count += 1
        logger.info(f"Task {task_id}: Leagues Task Complete: {created_count} created, {updated_count} updated.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Critical error in league fetching task. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id):
    """(Sub-task) Fetches events for a specific league."""
    task_id = self.request.id
    logger.info(f"Task {task_id}: Starting event fetch for league ID: {league_id}.")
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
                    defaults={'league': league, 'home_team': home_obj, 'away_team': away_obj, 'match_date': parser.isoparse(item['commence_time'])}
                )
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
    except League.DoesNotExist:
        logger.warning(f"Task {task_id}: League with ID {league_id} not found.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching events for league {league_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def process_leagues_and_dispatch_subtasks_task(self, previous_task_result=None):
    """Step 2: Iterates through leagues to dispatch odds and score updates."""
    task_id = self.request.id
    now = timezone.now()
    logger.info(f"Task {task_id}: Starting league processing and sub-task dispatch.")
    for league in League.objects.filter(active=True):
        if not league.last_fetched_events or league.last_fetched_events < (now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)):
            fetch_events_for_league_task.apply_async(args=[league.id])

        fixtures_needing_odds = FootballFixture.objects.filter(
            league=league, status=FootballFixture.FixtureStatus.SCHEDULED,
            match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
        ).filter(
            models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES))
        )
        event_ids_for_odds = list(fixtures_needing_odds.values_list('api_id', flat=True))
        
        if event_ids_for_odds:
            # 1. Fetch Featured Markets in batches
            if DEFAULT_ODDS_API_MARKETS:
                for i in range(0, len(event_ids_for_odds), ODDS_FETCH_EVENT_BATCH_SIZE):
                    batch = event_ids_for_odds[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
                    fetch_odds_for_event_batch_task.apply_async(args=[league.api_id, batch])
            
            # 2. Fetch Additional Markets for each event individually
            if ADDITIONAL_ODDS_API_MARKETS:
                for event_id in event_ids_for_odds:
                    fetch_additional_markets_task.apply_async(args=[event_id])
        
        fetch_scores_for_league_task.apply_async(args=[league.id])

@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """Main orchestrator task."""
    pipeline = chain(fetch_and_update_leagues_task.s(), process_leagues_and_dispatch_subtasks_task.s())
    pipeline.apply_async()
    return "Full data update pipeline initiated."

@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def fetch_additional_markets_task(self, event_id):
    """Fetches 'Additional Markets' for a single event."""
    task_id = self.request.id
    client = TheOddsAPIClient()
    logger.info(f"Task {task_id}: Fetching ADDITIONAL markets '{ADDITIONAL_ODDS_API_MARKETS}' for event {event_id}.")
    try:
        fixture = FootballFixture.objects.get(api_id=event_id)
        event_odds_data = client.get_event_odds(event_id, DEFAULT_ODDS_API_REGIONS, ADDITIONAL_ODDS_API_MARKETS)
        with transaction.atomic():
            for bookmaker_data in event_odds_data.get('bookmakers', []):
                bookmaker, _ = Bookmaker.objects.get_or_create(api_bookmaker_key=bookmaker_data['key'], defaults={'name': bookmaker_data['title']})
                for market_data in bookmaker_data.get('markets', []):
                    market_key = market_data['key']
                    Market.objects.filter(fixture_display=fixture, bookmaker=bookmaker, api_market_key=market_key).delete()
                    category, _ = MarketCategory.objects.get_or_create(name=market_key.replace("_", " ").title())
                    market_instance = Market.objects.create(
                        fixture_display=fixture, bookmaker=bookmaker, category=category,
                        api_market_key=market_key, last_updated_odds_api=parser.isoparse(market_data['last_update'])
                    )
                    for outcome_data in market_data.get('outcomes', []):
                        name, point = _parse_outcome_details(outcome_data['name'], market_key)
                        MarketOutcome.objects.create(market=market_instance, outcome_name=name, odds=outcome_data['price'], point_value=point)
            logger.info(f"Task {task_id}: Successfully processed additional markets for fixture {fixture.id}.")
    except TheOddsAPIException as e:
        if e.status_code == 422:
             logger.warning(f"Task {task_id}: 422 Error for event {event_id}. API may not support '{ADDITIONAL_ODDS_API_MARKETS}' for this event. Won't retry.")
        else:
            raise self.retry(exc=e)
    except FootballFixture.DoesNotExist:
        logger.warning(f"Task {task_id}: Fixture with API ID {event_id} not found.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching additional markets for event {event_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, sport_key, event_ids, markets=None, regions=None):
    """Fetches 'Featured Markets' odds for a batch of events."""
    task_id = self.request.id
    markets_to_fetch = markets or DEFAULT_ODDS_API_MARKETS
    client = TheOddsAPIClient()
    logger.info(f"Task {task_id}: Fetching FEATURED odds for {len(event_ids)} events for markets: '{markets_to_fetch}'.")
    try:
        odds_data = client.get_odds(sport_key, regions or DEFAULT_ODDS_API_REGIONS, markets_to_fetch, event_ids)
        if not odds_data: return
        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}
        with transaction.atomic():
            for event_data in odds_data:
                fixture = fixtures_map.get(event_data['id'])
                if not fixture: continue
                market_keys_to_clear = markets_to_fetch.split(',')
                Market.objects.filter(fixture_display=fixture, api_market_key__in=market_keys_to_clear).delete()
                for bookmaker_data in event_data.get('bookmakers', []):
                    bookmaker, _ = Bookmaker.objects.get_or_create(api_bookmaker_key=bookmaker_data['key'], defaults={'name': bookmaker_data['title']})
                    for market_data in bookmaker_data.get('markets', []):
                        market_key = market_data['key']
                        category, _ = MarketCategory.objects.get_or_create(name=market_key.replace("_", " ").title())
                        market_instance = Market.objects.create(
                            fixture_display=fixture, bookmaker=bookmaker, category=category,
                            api_market_key=market_key, last_updated_odds_api=parser.isoparse(market_data['last_update'])
                        )
                        for outcome_data in market_data.get('outcomes', []):
                            name, point = _parse_outcome_details(outcome_data['name'], market_key)
                            MarketOutcome.objects.create(market=market_instance, outcome_name=name, odds=outcome_data['price'], point_value=point)
                fixture.last_odds_update = timezone.now()
                fixture.save(update_fields=['last_odds_update'])
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching featured odds. Retrying batch...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id):
    """Fetches scores and updates status for a single league."""
    task_id = self.request.id
    now = timezone.now()
    try:
        league = League.objects.get(id=league_id)
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status__in=[FootballFixture.FixtureStatus.LIVE, FootballFixture.FixtureStatus.SCHEDULED]),
            models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lt=now - timedelta(minutes=10))
        )
        if not fixtures_to_check.exists(): return
        
        fixture_ids = list(fixtures_to_check.values_list('api_id', flat=True))
        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=fixture_ids)
        fixtures_map = {f.api_id: f for f in fixtures_to_check}

        for score_item in scores_data:
            fixture = fixtures_map.get(score_item['id'])
            if not fixture: continue
            with transaction.atomic():
                is_completed = score_item.get('completed', False) or (now - parser.isoparse(score_item['commence_time']) > timedelta(minutes=ASSUMED_COMPLETION_MINUTES))
                if is_completed and fixture.status != FootballFixture.FixtureStatus.FINISHED:
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_s = score['score']
                            if score['name'] == fixture.away_team.name: away_s = score['score']
                    fixture.home_team_score = int(home_s) if home_s is not None else None
                    fixture.away_team_score = int(away_s) if away_s is not None else None
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    fixture.save()
                    logger.info(f"STATUS CHANGE: Fixture {fixture.id} to FINISHED.")
                    chain(settle_outcomes_for_fixture_task.s(fixture.id), settle_bets_for_fixture_task.s(), settle_tickets_for_fixture_task.s()).apply_async()
                elif not is_completed and fixture.status == FootballFixture.FixtureStatus.SCHEDULED:
                    fixture.status = FootballFixture.FixtureStatus.LIVE
                    fixture.save()
                    logger.info(f"STATUS CHANGE: Fixture {fixture.id} to LIVE.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching scores for league {league_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id):
    """Settles all market outcomes for a finished fixture."""
    task_id = self.request.id
    logger.info(f"Task {task_id}: Starting outcome settlement for fixture ID: {fixture_id}.")
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, status=FootballFixture.FixtureStatus.FINISHED)
        home_score, away_score = fixture.home_team_score, fixture.away_team_score
        if home_score is None or away_score is None: return

        outcomes_to_update = []
        for market in fixture.markets.prefetch_related('outcomes'):
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'LOST'
                if market.api_market_key == 'h2h':
                    if (outcome.outcome_name == fixture.home_team.name and home_score > away_score) or \
                       (outcome.outcome_name == fixture.away_team.name and away_score > home_score) or \
                       (outcome.outcome_name.lower() == 'draw' and home_score == away_score):
                        new_status = 'WON'
                elif market.api_market_key in ['totals', 'alternate_totals'] and outcome.point_value is not None:
                    total_score = home_score + away_score
                    if 'over' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score > outcome.point_value else 'PUSH' if total_score == outcome.point_value else 'LOST'
                    elif 'under' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score < outcome.point_value else 'PUSH' if total_score == outcome.point_value else 'LOST'
                elif market.api_market_key == 'btts':
                    if (outcome.outcome_name == 'Yes' and home_score > 0 and away_score > 0) or \
                       (outcome.outcome_name == 'No' and not (home_score > 0 and away_score > 0)):
                        new_status = 'WON'

                if new_status != 'PENDING':
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)
        
        if outcomes_to_update:
            MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
            logger.info(f"Task {task_id}: Settled {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
        return fixture_id
    except Exception as e:
        logger.exception(f"Task {task_id}: Error settling outcomes for fixture {fixture_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id):
    """Settles all individual bets for a fixture."""
    if not fixture_id: return
    task_id = self.request.id
    try:
        bets_to_settle = Bet.objects.filter(market_outcome__market__fixture_display_id=fixture_id, status='PENDING').select_related('market_outcome')
        updated_bets = [bet for bet in bets_to_settle if bet.market_outcome.result_status != 'PENDING']
        for bet in updated_bets:
            bet.status = bet.market_outcome.result_status
        if updated_bets:
            Bet.objects.bulk_update(updated_bets, ['status'])
            logger.info(f"Task {task_id}: Settled {len(updated_bets)} bets for fixture {fixture_id}.")
        return fixture_id
    except Exception as e:
        logger.exception(f"Task {task_id}: Error settling bets for fixture {fixture_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id):
    """Settles all bet tickets related to a fixture."""
    if not fixture_id: return
    task_id = self.request.id
    try:
        ticket_ids = BetTicket.objects.filter(bets__market_outcome__market__fixture_display_id=fixture_id).distinct().values_list('id', flat=True)
        settled_count = 0
        for ticket_id in ticket_ids:
            ticket = BetTicket.objects.prefetch_related('bets').get(id=ticket_id)
            if ticket.status == 'PENDING' and all(b.status != 'PENDING' for b in ticket.bets.all()):
                ticket.settle_ticket()
                settled_count += 1
        if settled_count > 0:
            logger.info(f"Task {task_id}: Settled {settled_count} tickets related to fixture {fixture_id}.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Error settling tickets for fixture {fixture_id}. Retrying...")
        raise self.retry(exc=e)