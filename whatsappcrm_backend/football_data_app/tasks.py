import logging
from django.conf import settings
from celery import shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta
from decimal import Decimal
from typing import List, Dict, Any

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# --- Configuration ---
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us,au")
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals")
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
ASSUMED_COMPLETION_MINUTES = getattr(settings, 'THE_ODDS_API_ASSUMED_COMPLETION_MINUTES', 120)
MAX_EVENT_RETRIES = getattr(settings, 'THE_ODDS_API_MAX_EVENT_RETRIES', 3)
EVENT_RETRY_DELAY = getattr(settings, 'THE_ODDS_API_EVENT_RETRY_DELAY', 300)


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
            fixture=fixture, # Updated field name
            bookmaker=bookmaker,
            api_market_key=market_key,
            category=category,
            defaults={'last_updated_odds_api': parser.isoparse(market_data['last_update'])}
        )
        
        if not created: # If market existed, clear old outcomes before adding new ones
            market.outcomes.all().delete()
            
        outcomes_to_create = [
            MarketOutcome(
                market=market, 
                outcome_name=o['name'], 
                odds=Decimal(str(o['price'])),
                point_value=o.get('point') # Added point_value extraction
            )
            for o in market_data.get('outcomes', [])
        ]
        if outcomes_to_create:
            MarketOutcome.objects.bulk_create(outcomes_to_create)

# --- PIPELINE 1: Full Data Update (Leagues, Events, Odds) ---

@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """Main entry point for the data fetching pipeline."""
    logger.info("--- Starting Full Data Update Pipeline ---")
    # Chain:
    # 1. Fetch leagues (returns league_ids)
    # 2. Prepare and launch a chord:
    #    - Header: A group of fetch_events_for_league_task instances.
    #    - Body (Callback): dispatch_odds_fetching_after_events_task.
    pipeline = (
        fetch_and_update_leagues_task.s() |
        _prepare_and_launch_event_odds_chord.s() # New intermediate task
    )
    pipeline.apply_async()

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self, _=None):
    """Step 1: Fetches all available soccer leagues from the API."""
    logger.info("Step 1: Starting league update task.")
    client = TheOddsAPIClient()
    try:
        sports_data_from_api = client.get_sports(all_sports=True)
        if not sports_data_from_api:
            logger.warning("Step 1: No sports data received from The Odds API.")
            return []

        logger.info(f"Step 1: Received {len(sports_data_from_api)} items from /sports endpoint.")
        
        processed_league_ids = []
        soccer_leagues_found_count = 0

        for item in sports_data_from_api:
            api_league_key = item.get('key')
            api_group = item.get('group', '').lower() # Normalize to lowercase for comparison
            api_title = item.get('title')
            api_description = item.get('description')

            # logger.debug(f"Processing item: key={api_league_key}, group={api_group}, title={api_title}")

            if 'soccer' in api_group:
                soccer_leagues_found_count += 1
                league_obj, created = League.objects.update_or_create(
                    api_id=api_league_key,
                    defaults={
                        'name': api_description or api_title or api_league_key,
                        'sport_key': item.get('group'), # Store original casing if needed, or normalize
                        'sport_group_name': item.get('group').title() if item.get('group') else None,
                        'short_name': api_title,
                        'api_description': api_description,
                        'active': True
                    })
                processed_league_ids.append(league_obj.id)
        
        logger.info(f"Step 1: Found {soccer_leagues_found_count} soccer leagues from API data. Processed and returning {len(processed_league_ids)} league IDs.")
        return processed_league_ids
    except TheOddsAPIException as e:
        logger.exception(f"API error during league update: {e}")
        raise self.retry(exc=e)

@shared_task(name="football_data_app.tasks._prepare_and_launch_event_odds_chord")
def _prepare_and_launch_event_odds_chord(league_ids: List[int]):
    """
    Intermediate task: Receives league_ids, creates the event fetching group (chord header),
    and launches the chord with dispatch_odds_fetching_after_events_task as the callback.
    """
    if not league_ids:
        logger.warning("Chord Prep: No league IDs received. Skipping event/odds processing.")
        return

    logger.info(f"Chord Prep: Received {len(league_ids)} league IDs. Preparing event fetch group.")

    # This group of tasks will form the "header" of the chord.
    # Each task in this group will fetch events for one league.
    event_fetch_tasks_group = group([
        fetch_events_for_league_task.s(league_id) for league_id in league_ids
    ])

    # This is the "body" or callback of the chord. It will only run after all tasks
    # in event_fetch_tasks_group have completed.
    # immutable=True ensures it receives the list of results from the header tasks.
    odds_dispatch_callback = dispatch_odds_fetching_after_events_task.s(immutable=True)

    # Create and apply the chord
    # chord(header)(body)
    task_chord = chord(event_fetch_tasks_group)(odds_dispatch_callback)
    task_chord.apply_async()

    logger.info(f"Chord Prep: Chord for event fetching and odds dispatch has been applied for {len(league_ids)} leagues.")

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id: int):
    """Fetches and updates events (fixtures) for a single league."""
    logger.info(f"[EventFetch] START - Fetching events for league ID: {league_id}")
    events_processed_count = 0
    try:
        league = League.objects.get(id=league_id) # Ensure league exists
        client = TheOddsAPIClient()
        # Fetch events for the configured lead time to align with odds fetching
        events_data = client.get_events(sport_key=league.api_id, days_from_now=ODDS_LEAD_TIME_DAYS) 
        
        logger.info(f"[EventFetch] API returned {len(events_data) if events_data else 0} events for league ID: {league_id} (using API Key for league: {league.api_id})")
        
        if events_data: # Only proceed if there's data
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
                            # Ensure status is set, default is SCHEDULED in model
                        }
                    )
                    events_processed_count += 1
        
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"[EventFetch] SUCCESS - Processed {events_processed_count} events for league ID: {league_id}")
        return {"league_id": league_id, "status": "success", "events_processed": events_processed_count}
    except League.DoesNotExist:
        logger.error(f"[EventFetch] FAILED - League with ID {league_id} does not exist.")
        return {"league_id": league_id, "status": "error", "message": "League not found"}
    except TheOddsAPIException as e:
        logger.error(f"[EventFetch] FAILED - API error fetching events for league {league_id} (API Key: {league.api_id if 'league' in locals() else 'N/A'}): {e}", exc_info=True)
        # Let Celery handle retry based on task decorator
        raise self.retry(exc=e) 
    except Exception as e:
        logger.error(f"[EventFetch] FAILED - Unexpected error fetching events for league {league_id}: {e}", exc_info=True)
        # For unexpected errors, return an error status. 
        # Consider if retry is appropriate or if it should fail fast.
        return {"league_id": league_id, "status": "error", "message": str(e)}

@shared_task(bind=True)
def dispatch_odds_fetching_after_events_task(self, results_from_event_fetches):
    """
    Step 3 (Chord Body): Dispatches parallel tasks to fetch odds for upcoming fixtures
    after all event fetching tasks (from the chord header) have completed.
    """
    # results_from_event_fetches will be a list of return values from each fetch_events_for_league_task.
    # Example: [{'league_id': 1, 'status': 'success', 'events_processed': 5}, {'league_id': 2, ...}]
    logger.info(
        f"Step 3: Dispatching odds. Received {len(results_from_event_fetches)} result(s) from the event fetching group."
    )
    if results_from_event_fetches:
        # Log a summary or sample of the results, not the whole thing if it's huge
        logger.debug(f"Step 3: Sample of results_from_event_fetches: {str(results_from_event_fetches)[:500]}")
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)
    
    fixtures_to_update = FootballFixture.objects.filter(
        # Fetch for fixtures that have never had odds updated OR are stale (Q object first)
        models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=stale_cutoff),
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
    ).values('league_id', 'api_id', 'league__api_id') # Include league.api_id for the client
 
    if not fixtures_to_update:
        logger.info("No fixtures require an odds update at this time.")
        return

    # Group fixtures by league's API ID (sport_key for the API) to batch API calls
    fixtures_by_sport_key = {}
    for item in fixtures_to_update:
        fixtures_by_sport_key.setdefault(item['league__api_id'], []).append(item['api_id'])

    tasks = []
    for sport_key, event_ids_for_league in fixtures_by_sport_key.items():
        # Batch event_ids further if needed, based on ODDS_FETCH_EVENT_BATCH_SIZE
        for i in range(0, len(event_ids_for_league), ODDS_FETCH_EVENT_BATCH_SIZE):
            batch_ids = event_ids_for_league[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
            tasks.append(fetch_odds_for_event_batch_task.s(
                sport_key=sport_key, # Pass the league's api_id as sport_key
                event_ids=batch_ids
            ))

    if tasks:
        group(tasks).apply_async()
        logger.info(f"Dispatched {len(tasks)} odds fetching tasks in batches.")
    else:
        logger.info("No odds fetching tasks were dispatched (possibly all fixtures up-to-date or no upcoming).")

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, sport_key: str, event_ids: List[str]):
    """Fetches default market odds for a batch of events."""
    logger.info(f"Fetching odds for {len(event_ids)} events using sport_key: {sport_key}.")
    client = TheOddsAPIClient()
    try:
        # league = League.objects.get(api_id=sport_key) # Not strictly needed if client uses sport_key directly
        odds_data = client.get_odds(sport_key, DEFAULT_ODDS_API_REGIONS, DEFAULT_ODDS_API_MARKETS, event_ids)
        
        if not odds_data:
            return

        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}
        for event_data in odds_data:
            if fixture := fixtures_map.get(event_data['id']):
                with transaction.atomic():
                    for bookmaker_data in event_data.get('bookmakers', []):
                        _process_bookmaker_data(fixture, bookmaker_data, DEFAULT_ODDS_API_MARKETS.split(','))
                    fixture.last_odds_update = timezone.now()
                    fixture.save(update_fields=['last_odds_update'])

    except TheOddsAPIException as e:
        logger.exception(f"API error in odds fetch batch: {e}")
        raise self.retry(exc=e)

# --- PIPELINE 2: Score Fetching and Settlement ---

@shared_task(name="football_data_app.run_score_and_settlement_task")
def run_score_and_settlement_task():
    """Dedicated entry point for fetching scores and updating statuses."""
    logger.info("--- Starting Score & Settlement Pipeline ---")
    active_leagues = League.objects.filter(active=True).values_list('id', flat=True)
    tasks = [fetch_scores_for_league_task.s(league_id) for league_id in active_leagues]
    if tasks:
        group(tasks).apply_async()
        logger.info(f"Dispatched {len(tasks)} score fetching tasks.")

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id: int):
    """Fetches scores for a league and updates fixture statuses (Live/Finished)."""
    logger.info(f"Fetching scores for league ID: {league_id}")
    now = timezone.now()
    try:
        league = League.objects.get(id=league_id)
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(league=league, status=FootballFixture.FixtureStatus.SCHEDULED, match_date__lt=now)
        ).values_list('api_id', flat=True)

        if not fixtures_to_check.exists():
            return

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=list(fixtures_to_check))
        
        for score_item in scores_data:
            with transaction.atomic():
                fixture = FootballFixture.objects.select_for_update().get(api_id=score_item['id'])
                if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                    continue

                logger.info(f"Processing score for fixture {fixture.api_id}, current status: {fixture.status}")
                logger.info(f"API commence_time: {score_item.get('commence_time')}, fixture match_date: {fixture.match_date}, now: {now}")


                if score_item.get('completed', False):
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_s = score['score']
                            elif score['name'] == fixture.away_team.name: away_s = score['score']
                    
                    fixture.home_team_score = int(home_s) if home_s is not None else None
                    fixture.away_team_score = int(away_s) if away_s is not None else None
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    fixture.save()
                    logger.info(f"Fixture {fixture.id} marked as FINISHED. Triggering settlement.")
                    settle_fixture_pipeline_task.delay(fixture.id)
                else:
                    if fixture.status == FootballFixture.FixtureStatus.SCHEDULED and parser.isoparse(score_item['commence_time']) <= now:
                        fixture.status = FootballFixture.FixtureStatus.LIVE
                        fixture.save()
                        logger.info(f"Fixture {fixture.id} marked as LIVE.")
    except League.DoesNotExist:
        logger.error(f"League {league_id} not found for score update.")
    except TheOddsAPIException as e:
        if e.status_code == 401:
            logger.warning(f"API key has insufficient quota. Aborting scores fetch for league {league_id}.")
            return
        logger.exception(f"API error fetching scores for league {league_id}: {e}")
        raise self.retry(exc=e)

@shared_task(name="football_data_app.settle_fixture_pipeline")
def settle_fixture_pipeline_task(fixture_id: int):
    """Creates a settlement chain (outcomes -> bets -> tickets) for a single finished fixture."""
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
            return fixture_id
            
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
                        if total_score > outcome.point_value: new_status = 'WON'
                        elif total_score == outcome.point_value: new_status = 'PUSH'
                    elif 'under' in outcome.outcome_name.lower():
                        if total_score < outcome.point_value: new_status = 'WON'
                        elif total_score == outcome.point_value: new_status = 'PUSH'
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
    if not fixture_id: return
    logger.info(f"Settling bets for fixture ID: {fixture_id}")
    try:
        bets = Bet.objects.filter(
            market_outcome__market__fixture_id=fixture_id, # Updated field name
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
def settle_tickets_for_fixture_task(self, fixture_id: int):
    """Settles bet tickets based on bet statuses."""
    if not fixture_id: return
    logger.info(f"Settling tickets for fixture ID: {fixture_id}")
    try:
        ticket_ids = BetTicket.objects.filter(
            bets__market_outcome__market__fixture_id=fixture_id # Updated field name
        ).distinct().values_list('id', flat=True)
        
        for ticket_id in ticket_ids:
            ticket = BetTicket.objects.prefetch_related('bets').get(id=ticket_id)
            if ticket.status == 'PENDING' and not ticket.bets.filter(status='PENDING').exists():
                ticket.settle_ticket()
    except Exception as e:
        logger.exception(f"Error settling tickets for fixture {fixture_id}")
        raise self.retry(exc=e)