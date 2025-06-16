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
    """
    Parses an outcome name to extract the name and point value, especially for totals and spreads markets.
    """
    name_part, point_part = outcome_name, None
    if market_key in ['totals', 'spreads', 'alternate_totals']:
        try:
            parts = outcome_name.split()
            last_part = parts[-1]
            if last_part.replace('.', '', 1).lstrip('+-').isdigit():
                point_part = float(last_part)
                name_part = " ".join(parts[:-1]) or outcome_name
        except (ValueError, IndexError) as e:
            logger.debug(f"Could not parse point from '{outcome_name}' for market '{market_key}': {e}")
    return name_part, point_part

@transaction.atomic
def _process_bookmaker_data(fixture: FootballFixture, bookmaker_data: dict, market_keys: List[str]):
    """
    Processes and saves market and outcome data for a given fixture and bookmaker.
    This function is designed to be atomic to ensure data integrity.
    """
    bookmaker, _ = Bookmaker.objects.get_or_create(
        api_bookmaker_key=bookmaker_data['key'],
        defaults={'name': bookmaker_data['title']}
    )
    
    for market_data in bookmaker_data.get('markets', []):
        market_key = market_data['key']
        if market_key not in market_keys:
            continue
            
        category, _ = MarketCategory.objects.get_or_create(
            name=market_key.replace("_", " ").title()
        )
        
        market, created = Market.objects.update_or_create(
            fixture_display=fixture,
            bookmaker=bookmaker,
            api_market_key=market_key,
            category=category,
            defaults={'last_updated_odds_api': parser.isoparse(market_data['last_update'])}
        )
        
        # If the market is not new, clear out old outcomes to ensure freshness
        if not created:
            market.outcomes.all().delete()
            
        outcomes_to_create = []
        for outcome_data in market_data.get('outcomes', []):
            name, point = _parse_outcome_details(outcome_data['name'], market_key)
            outcomes_to_create.append(
                MarketOutcome(
                    market=market,
                    outcome_name=name,
                    odds=Decimal(str(outcome_data['price'])),
                    point_value=point
                )
            )
        MarketOutcome.objects.bulk_create(outcomes_to_create)

# --- Core Data Fetching Tasks ---
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """
    Step 1: Fetches all available soccer leagues from the API and updates the database.
    This is the entry point for the entire data update pipeline.
    """
    logger.info("Starting league fetching task...")
    client = TheOddsAPIClient()
    try:
        sports_data = client.get_sports(all_sports=True)
        for item in sports_data:
            if 'soccer' in item.get('group', ''):
                League.objects.update_or_create(
                    api_id=item['key'],
                    defaults={
                        'name': item.get('title', 'Unknown League'),
                        'sport_key': item.get('group', 'soccer'),
                        'active': True
                    }
                )
        logger.info("League fetching task completed successfully.")
        return [league.id for league in League.objects.filter(active=True)]
    except TheOddsAPIException as e:
        logger.exception(f"API error in league fetching (Task ID: {self.request.id}): {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Critical error in league fetching (Task ID: {self.request.id}): {e}")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id: int):
    """
    Step 2a: For a single league, fetches all upcoming events (fixtures).
    """
    logger.info(f"Fetching events for league ID: {league_id}")
    try:
        league = League.objects.get(id=league_id)
        client = TheOddsAPIClient()
        events_data = client.get_events(sport_key=league.api_id)
        
        with transaction.atomic():
            for item in events_data:
                if not item.get('home_team') or not item.get('away_team'):
                    continue
                    
                home_team, _ = Team.objects.get_or_create(name=item['home_team'])
                away_team, _ = Team.objects.get_or_create(name=item['away_team'])
                
                FootballFixture.objects.update_or_create(
                    api_id=item['id'],
                    defaults={
                        'league': league,
                        'home_team': home_team,
                        'away_team': away_team,
                        'match_date': parser.isoparse(item['commence_time']),
                        'status': FootballFixture.FixtureStatus.SCHEDULED
                    }
                )
        
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Successfully fetched events for league ID: {league_id}")
    except League.DoesNotExist:
        logger.error(f"League with ID {league_id} does not exist. Aborting task.")
    except TheOddsAPIException as e:
        logger.exception(f"API error fetching events for league {league_id}: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"General error fetching events for league {league_id}: {e}")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, league_id: int, event_ids: List[str], markets: str, regions: str):
    """
    Step 2b: Fetches main market odds for a batch of events within a league.
    """
    logger.info(f"Fetching odds for {len(event_ids)} events in league {league_id} for markets '{markets}'")
    client = TheOddsAPIClient()
    try:
        league = League.objects.get(id=league_id)
        odds_data = client.get_odds(
            league.api_id,
            regions,
            markets,
            event_ids,
            bookmakers=TARGET_BOOKMAKER
        )
        
        if not odds_data:
            logger.info(f"No odds data returned for this batch of events.")
            return

        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}
        
        for event_data in odds_data:
            fixture = fixtures_map.get(event_data['id'])
            if not fixture:
                continue
                
            with transaction.atomic():
                for bookmaker_data in event_data.get('bookmakers', []):
                    _process_bookmaker_data(fixture, bookmaker_data, markets.split(','))
                
                fixture.last_odds_update = timezone.now()
                fixture.save(update_fields=['last_odds_update'])

    except League.DoesNotExist:
        logger.error(f"League with ID {league_id} not found during odds fetch.")
    except TheOddsAPIException as e:
        logger.error(f"API error fetching odds batch: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Critical error processing odds batch: {e}")
        raise self.retry(exc=e)


# --- Score and Settlement Tasks ---

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id: int):
    """
    Step 3a: Fetches and processes scores for live or recently scheduled fixtures in a given league.
    """
    logger.info(f"Fetching scores for league ID: {league_id}")
    now = timezone.now()
    try:
        league = League.objects.get(id=league_id)
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(league=league, status=FootballFixture.FixtureStatus.SCHEDULED, match_date__lt=now)
        ).distinct()

        if not fixtures_to_check.exists():
            return

        event_ids_to_fetch = list(fixtures_to_check.values_list('api_id', flat=True))
        if not event_ids_to_fetch:
            return

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=event_ids_to_fetch)

        for score_item in scores_data:
            with transaction.atomic():
                fixture = FootballFixture.objects.select_for_update().get(api_id=score_item['id'])
                if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                    continue

                if score_item.get('completed', False):
                    home_score, away_score = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name:
                                home_score = score['score']
                            elif score['name'] == fixture.away_team.name:
                                away_score = score['score']
                    
                    fixture.home_team_score = int(home_score) if home_score is not None else None
                    fixture.away_team_score = int(away_score) if away_score is not None else None
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    fixture.save()
                    
                    # Trigger the settlement process for the finished fixture
                    settle_fixture_pipeline_task.delay(fixture.id)
                else:
                    # If game has started but status is still 'scheduled', mark it as 'live'
                    if fixture.status == FootballFixture.FixtureStatus.SCHEDULED and parser.isoparse(score_item['commence_time']) <= now:
                        fixture.status = FootballFixture.FixtureStatus.LIVE
                        fixture.save()

    except League.DoesNotExist:
        logger.error(f"Cannot fetch scores, league {league_id} not found.")
    except TheOddsAPIException as e:
        logger.error(f"API error fetching scores for league {league_id}: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Error fetching scores for league {league_id}: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id: int):
    """
    Step 3b (i): Determines the outcome statuses (WON, LOST, PUSH) for a finished fixture.
    """
    logger.info(f"Settling outcomes for fixture ID: {fixture_id}")
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, status=FootballFixture.FixtureStatus.FINISHED)
        if fixture.home_team_score is None or fixture.away_team_score is None:
            logger.warning(f"Cannot settle outcomes for fixture {fixture_id}, final score is missing.")
            return

        home_s, away_s = fixture.home_team_score, fixture.away_team_score
        total = home_s + away_s
        outcomes_to_update = []

        for market in fixture.markets.prefetch_related('outcomes'):
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'LOST'
                market_key = market.api_market_key

                if market_key == 'h2h':
                    if (outcome.outcome_name == fixture.home_team.name and home_s > away_s) or \
                       (outcome.outcome_name == fixture.away_team.name and away_s > home_s) or \
                       (outcome.outcome_name.lower() == 'draw' and home_s == away_s):
                        new_status = 'WON'
                elif market_key in ['totals', 'alternate_totals'] and outcome.point_value is not None:
                    if 'over' in outcome.outcome_name.lower():
                        if total > outcome.point_value: new_status = 'WON'
                        elif total == outcome.point_value: new_status = 'PUSH'
                    elif 'under' in outcome.outcome_name.lower():
                        if total < outcome.point_value: new_status = 'WON'
                        elif total == outcome.point_value: new_status = 'PUSH'
                elif market_key == 'btts':
                    if (outcome.outcome_name == 'Yes' and home_s > 0 and away_s > 0) or \
                       (outcome.outcome_name == 'No' and not (home_s > 0 and away_s > 0)):
                        new_status = 'WON'
                
                if new_status != 'PENDING':
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)

        if outcomes_to_update:
            MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
        logger.info(f"Successfully settled {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
        return fixture_id
    except FootballFixture.DoesNotExist:
        logger.warning(f"Could not find fixture {fixture_id} to settle outcomes.")
    except Exception as e:
        logger.exception(f"Error settling outcomes for fixture {fixture_id}: {e}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id: int):
    """
    Step 3b (ii): Updates individual bet statuses based on the settled outcomes.
    """
    if not fixture_id: return
    logger.info(f"Settling bets for fixture ID: {fixture_id}")
    bets_to_update = []
    try:
        bets = Bet.objects.filter(
            market_outcome__market__fixture_display_id=fixture_id,
            status='PENDING'
        ).select_related('market_outcome')

        for bet in bets:
            if bet.market_outcome.result_status != 'PENDING':
                bet.status = bet.market_outcome.result_status
                bets_to_update.append(bet)
        
        if bets_to_update:
            Bet.objects.bulk_update(bets_to_update, ['status'])
        logger.info(f"Successfully settled {len(bets_to_update)} bets for fixture {fixture_id}.")
        return fixture_id
    except Exception as e:
        logger.exception(f"Error settling bets for fixture {fixture_id}: {e}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id: int):
    """
    Step 3b (iii): Settles all betting tickets associated with the fixture.
    """
    if not fixture_id: return
    logger.info(f"Settling tickets related to fixture ID: {fixture_id}")
    try:
        ticket_ids = BetTicket.objects.filter(
            bets__market_outcome__market__fixture_display_id=fixture_id
        ).distinct().values_list('id', flat=True)

        for ticket_id in ticket_ids:
            with transaction.atomic():
                ticket = BetTicket.objects.select_for_update().get(id=ticket_id)
                if ticket.status == 'PENDING' and not ticket.bets.filter(status='PENDING').exists():
                    ticket.settle_ticket()
        logger.info(f"Successfully processed tickets for fixture {fixture_id}.")
    except Exception as e:
        logger.exception(f"Error settling tickets for fixture {fixture_id}: {e}")
        raise self.retry(exc=e)


# --- Orchestration Tasks ---

@shared_task
def dispatch_league_subtasks(league_ids: List[int]):
    """
    Dispatches event and odds fetching tasks for all active leagues in parallel.
    """
    if not league_ids:
        logger.info("No active leagues to process.")
        return

    # Create a group of tasks to fetch events for all leagues in parallel
    event_fetching_group = group(
        fetch_events_for_league_task.s(league_id) for league_id in league_ids
    )
    
    # After event fetching, proceed to fetch odds.
    pipeline = chain(
        event_fetching_group,
        dispatch_odds_fetching_for_all_leagues_task.s()
    )
    pipeline.apply_async()


@shared_task
def dispatch_odds_fetching_for_all_leagues_task():
    """
    Finds fixtures that need an odds update and dispatches tasks in batches.
    """
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)
    
    leagues = League.objects.filter(active=True)
    for league in leagues:
        fixtures_needing_update = FootballFixture.objects.filter(
            league=league,
            status=FootballFixture.FixtureStatus.SCHEDULED,
            match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
        ).filter(
            models.Q(last_odds_update__isnull=True) |
            models.Q(last_odds_update__lt=stale_cutoff)
        ).values_list('api_id', flat=True)
        
        event_ids = list(fixtures_needing_update)

        if event_ids:
            # Batch fetch main markets
            for i in range(0, len(event_ids), ODDS_FETCH_EVENT_BATCH_SIZE):
                batch = event_ids[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
                fetch_odds_for_event_batch_task.delay(
                    league_id=league.id,
                    event_ids=batch,
                    markets=DEFAULT_ODDS_API_MARKETS,
                    regions=DEFAULT_ODDS_API_REGIONS
                )

@shared_task(name="football_data_app.run_score_update_task")
def run_score_update_task():
    """
    Step 3: Creates a group of tasks to fetch scores for all active leagues in parallel.
    """
    logger.info("Starting score update process for all active leagues.")
    tasks = [fetch_scores_for_league_task.s(league.id) for league in League.objects.filter(active=True)]
    group(tasks).apply_async()


@shared_task(name="football_data_app.settle_fixture_pipeline")
def settle_fixture_pipeline_task(fixture_id: int):
    """
    Creates a settlement chain for a single finished fixture.
    """
    pipeline = chain(
        settle_outcomes_for_fixture_task.s(fixture_id),
        settle_bets_for_fixture_task.s(),
        settle_tickets_for_fixture_task.s()
    )
    pipeline.apply_async()

@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """
    Main entry point for the entire data update process.
    Orchestrates fetching leagues, events, odds, and scores in a robust, sequential pipeline.
    """
    pipeline = chain(
        # Step 1: Get all the latest league data. Returns a list of league IDs.
        fetch_and_update_leagues_task.s(),
        
        # Step 2: Dispatch parallel subtasks for events and odds for all leagues.
        dispatch_league_subtasks.s(),
        
        # Step 3: Run the parallel score update process.
        run_score_update_task.s()
    )
    pipeline.apply_async()