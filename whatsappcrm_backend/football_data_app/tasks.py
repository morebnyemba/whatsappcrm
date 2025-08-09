import logging
from django.conf import settings
from celery import chord, shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta
from decimal import Decimal
from typing import List, Dict, Any
import random
import time

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .utils import settle_ticket # Import the new utility function
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

from meta_integration.models import MetaAppConfig
# Use the direct utility for sending messages for consistency
from meta_integration.utils import send_whatsapp_message, create_text_message_data

logger = logging.getLogger(__name__)

# --- Configuration ---
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us,au")
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals")
# List of additional markets to fetch alongside the default ones.
ADDITIONAL_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_ADDITIONAL_MARKETS', "alternate_totals,btts")
PREFERRED_ODDS_API_BOOKMAKERS = getattr(settings, 'THE_ODDS_API_PREFERRED_BOOKMAKERS', "bet365")
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
ASSUMED_COMPLETION_MINUTES = getattr(settings, 'THE_ODDS_API_ASSUMED_COMPLETION_MINUTES', 120)
MAX_EVENT_RETRIES = getattr(settings, 'THE_ODDS_API_MAX_EVENT_RETRIES', 3)
EVENT_RETRY_DELAY = getattr(settings, 'THE_ODDS_API_EVENT_RETRY_DELAY', 300)


# --- Helper Functions ---
@transaction.atomic
def _process_bookmaker_data(fixture: FootballFixture, bookmaker_data: dict):
    """
    Processes and saves market and outcome data for a given fixture and bookmaker.
    Assumes that old markets for this bookmaker/fixture have been cleared by the calling task.
    """
    bookmaker, _ = Bookmaker.objects.get_or_create(
        api_bookmaker_key=bookmaker_data['key'],
        defaults={'name': bookmaker_data['title']}
    )

    for market_data in bookmaker_data.get('markets', []):
        market_key = market_data['key']
        category, _ = MarketCategory.objects.get_or_create(name=market_key.replace("_", " ").title())

        # Since old markets are cleared by the calling task, we can simply create new ones.
        market = Market.objects.create(
            fixture=fixture,
            bookmaker=bookmaker,
            api_market_key=market_key,
            category=category,
            last_updated_odds_api=parser.isoparse(market_data['last_update'])
        )

        outcomes_to_create = [
            MarketOutcome(
                market=market,
                outcome_name=o['name'],
                odds=Decimal(str(o['price'])),
                point_value=o.get('point')
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
    # It automatically receives the list of results from the header tasks as its first argument.
    odds_dispatch_callback = dispatch_odds_fetching_after_events_task.s()

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
    Step 3 (Chord Body): Dispatches individual tasks to fetch odds for each upcoming fixture
    after all event fetching tasks (from the chord header) have completed.
    """
    logger.info(
        f"Step 3: Dispatching odds. Received {len(results_from_event_fetches)} result(s) from the event fetching group."
    )
    if results_from_event_fetches:
        logger.debug(f"Step 3: Sample of results_from_event_fetches: {str(results_from_event_fetches)[:500]}")

    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)

    # Get a list of fixture IDs that need an odds update.
    fixture_ids_to_update = FootballFixture.objects.filter(
        models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=stale_cutoff),
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
    ).values_list('id', flat=True)

    if not fixture_ids_to_update:
        logger.info("No fixtures require an odds update at this time.")
        return

    # Create a group of tasks, one for each fixture.
    tasks = [fetch_odds_for_single_event_task.s(fixture_id) for fixture_id in fixture_ids_to_update]

    if tasks:
        group(tasks).apply_async()
        logger.info(f"Dispatched {len(tasks)} individual odds fetching tasks for fixtures.")
    else:
        logger.info("No odds fetching tasks were dispatched (possibly all fixtures up-to-date or no upcoming).")

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_single_event_task(self, fixture_id: int):
    """Fetches all available markets for a single fixture using the dedicated event odds endpoint."""
    # --- PERFORMANCE FIX: Add jitter to spread out API requests ---
    # This prevents overwhelming the API with a large burst of simultaneous requests.
    # Since gevent is used, time.sleep is non-blocking.
    time.sleep(random.uniform(0.5, 3.0))
    # --- END FIX ---

    try:
        fixture = FootballFixture.objects.select_related('league').get(id=fixture_id)
        logger.info(f"[SingleEventOdds] START - Fetching odds for fixture ID: {fixture.id} (API Event ID: {fixture.api_id})")

        client = TheOddsAPIClient()

        # Combine default and additional markets into a single comma-separated string for the API
        markets_to_fetch = f"{DEFAULT_ODDS_API_MARKETS},{ADDITIONAL_ODDS_API_MARKETS}".strip(',')

        logger.debug(
            f"[SingleEventOdds] Calling get_event_odds for fixture {fixture.id} "
            f"with sport_key='{fixture.league.api_id}', event_id='{fixture.api_id}', markets='{markets_to_fetch}'"
        )

        # Use the updated client method for single event odds
        odds_data = client.get_event_odds(
            sport_key=fixture.league.api_id,
            event_id=fixture.api_id,
            regions=DEFAULT_ODDS_API_REGIONS,
            markets=markets_to_fetch,
            bookmakers=PREFERRED_ODDS_API_BOOKMAKERS
        )

        if not odds_data:
            logger.info(f"[SingleEventOdds] No odds data returned from API for fixture {fixture.id}. This may be normal if no odds are available.")
            # We can still update the timestamp to avoid re-checking immediately
            fixture.last_odds_update = timezone.now()
            fixture.save(update_fields=['last_odds_update'])
            return {"fixture_id": fixture.id, "status": "no_odds_data"}

        # The data structure is a single event object
        with transaction.atomic():
            # Re-fetch fixture with lock to prevent race conditions during update
            fixture_for_update = FootballFixture.objects.select_for_update().get(id=fixture.id)

            # Get a list of bookmaker keys present in the new API data
            bookmaker_keys_in_response = {bk['key'] for bk in odds_data.get('bookmakers', [])}

            # Delete markets for this fixture from bookmakers that are in the API response.
            # This ensures we are replacing their data with the latest, without touching
            # data from other bookmakers not in this specific API response.
            if bookmaker_keys_in_response:
                deleted_count, _ = Market.objects.filter(
                    fixture=fixture_for_update,
                    bookmaker__api_bookmaker_key__in=bookmaker_keys_in_response
                ).delete()
                logger.debug(
                    f"[SingleEventOdds] Cleared {deleted_count} existing market(s) for fixture {fixture.id} "
                    f"from bookmakers: {bookmaker_keys_in_response}."
                )

            for bookmaker_data in odds_data.get('bookmakers', []):
                _process_bookmaker_data(fixture_for_update, bookmaker_data)

            fixture_for_update.last_odds_update = timezone.now()
            fixture_for_update.save(update_fields=['last_odds_update'])
            logger.info(f"[SingleEventOdds] SUCCESS - Successfully processed and saved odds for fixture {fixture.id}.")
            return {"fixture_id": fixture.id, "status": "success"}

    except FootballFixture.DoesNotExist:
        logger.error(f"[SingleEventOdds] FAILED - Fixture with ID {fixture_id} not found.")
        return {"fixture_id": fixture_id, "status": "error", "message": "Fixture not found"}
    except TheOddsAPIException as e:
        logger.exception(f"[SingleEventOdds] FAILED - API error fetching odds for fixture {fixture_id}: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"[SingleEventOdds] FAILED - Unexpected error for fixture {fixture_id}: {e}")
        raise self.retry(exc=e)

# --- PIPELINE 3: Reconciliation and Cleanup ---

@shared_task(name="football_data_app.process_ticket_settlement_task")
def process_ticket_settlement_task(ticket_id: int):
    """
    Celery task to process the settlement of a single bet ticket.
    This should be called after any bet on the ticket is updated.
    It calls the main settlement utility function.
    """
    logger.info(f"Starting settlement process for BetTicket ID: {ticket_id}")
    try:
        # This function now contains all the logic for checking, settling, and paying out.
        settle_ticket(ticket_id)
    except Exception as e:
        logger.error(f"Error during settlement for BetTicket ID {ticket_id}: {e}", exc_info=True)

@shared_task(name="football_data_app.process_ticket_settlement_batch_task")
def process_ticket_settlement_batch_task(ticket_ids: List[int]):
    """
    Processes a batch of bet tickets for settlement.
    This is more efficient than creating one task per ticket.
    """
    logger.info(f"Processing settlement for a batch of {len(ticket_ids)} tickets.")
    for ticket_id in ticket_ids:
        try:
            settle_ticket(ticket_id)
        except Exception as e:
            logger.error(f"Error during batch settlement for BetTicket ID {ticket_id}: {e}", exc_info=True)

@shared_task(bind=True, name="football_data_app.reconcile_and_settle_pending_items")
def reconcile_and_settle_pending_items_task(self):
    """
    A periodic task to find and settle any bets or tickets that might have been missed
    by the event-driven settlement pipeline. It also force-settles "stuck" fixtures.

    This task should be scheduled to run periodically (e.g., every 5-10 minutes)
    using a scheduler like Celery Beat.
    """
    logger.info("[Reconciliation] START - Running reconciliation and settlement task.")

    # --- Step 0: Find and force-settle stuck fixtures with pending bets ---
    now = timezone.now()
    stuck_fixture_cutoff = now - timedelta(minutes=ASSUMED_COMPLETION_MINUTES)

    stuck_fixtures_qs = FootballFixture.objects.filter(
        markets__outcomes__bets__status='PENDING'
    ).filter(
        status__in=[FootballFixture.FixtureStatus.SCHEDULED, FootballFixture.FixtureStatus.LIVE],
        match_date__lt=stuck_fixture_cutoff
    ).distinct()

    stuck_fixtures_triggered_count = 0
    if stuck_fixtures_qs.exists():
        logger.warning(f"[Reconciliation] Found {stuck_fixtures_qs.count()} stuck fixtures with pending bets. Forcing settlement check.")
        for fixture in stuck_fixtures_qs:
            with transaction.atomic():
                fixture_to_settle = FootballFixture.objects.select_for_update().get(id=fixture.id)
                if fixture_to_settle.status not in [FootballFixture.FixtureStatus.SCHEDULED, FootballFixture.FixtureStatus.LIVE]:
                    continue

                logger.warning(f"[Reconciliation] Force-settling stuck fixture ID: {fixture.id} ({fixture_to_settle}).")
                if fixture_to_settle.home_team_score is None:
                    fixture_to_settle.home_team_score = 0
                if fixture_to_settle.away_team_score is None:
                    fixture_to_settle.away_team_score = 0
                
                fixture_to_settle.status = FootballFixture.FixtureStatus.FINISHED
                fixture_to_settle.save(update_fields=['status', 'home_team_score', 'away_team_score'])
                
                settle_fixture_pipeline_task.delay(fixture_to_settle.id)
                stuck_fixtures_triggered_count += 1

    # --- Step 1: Settle individual bets whose outcomes are now resolved ---
    # Find all pending bets whose outcomes are already settled.
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
                logger.info(f"[Reconciliation] Settled {bets_updated_count} individual bets whose outcomes were resolved.")

    # --- Step 2: Settle bet tickets that are now fully resolved ---
    # Find all pending tickets and check if they are now fully resolved.
    ticket_ids_to_check = list(BetTicket.objects.filter(status='PENDING').values_list('id', flat=True))

    tickets_settled_count = 0
    if ticket_ids_to_check:
        # PERFORMANCE FIX: Use chunks to batch process tickets, avoiding a "task storm".
        process_ticket_settlement_batch_task.chunks(zip(ticket_ids_to_check), 100).apply_async()
        tickets_settled_count = len(ticket_ids_to_check)
        logger.info(f"[Reconciliation] Dispatched {tickets_settled_count} tickets for settlement in batches of 100.")

    logger.info(f"[Reconciliation] FINISHED - Stuck Fixtures Triggered: {stuck_fixtures_triggered_count}, Bets updated: {bets_updated_count}, Tickets dispatched for settlement: {tickets_settled_count}.")

# --- PIPELINE 2: Score Fetching and Settlement ---

@shared_task(name="football_data_app.run_score_and_settlement_task")
def run_score_and_settlement_task():
    """Dedicated entry point for fetching scores and updating statuses."""
    logger.info("--- Starting Score & Settlement Pipeline ---") # Log message for clarity
    active_leagues = League.objects.filter(active=True).values_list('id', flat=True)
    tasks = [fetch_scores_for_league_task.s(league_id) for league_id in active_leagues]
    if tasks:
        group(tasks).apply_async()
        logger.info(f"Dispatched {len(tasks)} score fetching tasks.")

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id: int):
    """
    Fetches scores for a league, updates fixture statuses (Live/Finished),
    and marks overdue matches as finished.
    """
    logger.info(f"[Scores] START - Fetching scores for league ID: {league_id}")
    now = timezone.now()
    # Cutoff time for when a match is assumed to be completed if no API data is available.
    assumed_completion_cutoff = now - timedelta(minutes=ASSUMED_COMPLETION_MINUTES)

    try:
        league = League.objects.get(id=league_id)

        # Get all fixtures that are potentially in-play or recently finished.
        # This includes LIVE matches and SCHEDULED matches that should have started.
        fixtures_to_check_qs = FootballFixture.objects.filter(
            league=league
        ).filter(
            models.Q(status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(
                status=FootballFixture.FixtureStatus.SCHEDULED,
                match_date__lt=now  # Match should have started
            )
        )

        if not fixtures_to_check_qs.exists():
            logger.info(f"[Scores] No fixtures need a score update for league ID: {league_id}.")
            return

        fixture_api_ids_to_check = list(fixtures_to_check_qs.values_list('api_id', flat=True))
        logger.info(f"[Scores] Checking {len(fixture_api_ids_to_check)} fixtures for league {league_id}.")

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=fixture_api_ids_to_check)

        processed_api_ids = set()

        if not scores_data:
            logger.info(f"[Scores] The Odds API returned no score data for league {league_id}. Proceeding to check for overdue fixtures.")
        else:
            for score_item in scores_data:
                processed_api_ids.add(score_item['id'])
                try:
                    with transaction.atomic():
                        fixture = FootballFixture.objects.select_for_update().get(api_id=score_item['id'])
                        if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                            continue

                        home_s, away_s = None, None
                        if score_item.get('scores'):
                            for score in score_item['scores']:
                                if score['name'] == score_item.get('home_team'): home_s = score['score']
                                elif score['name'] == score_item.get('away_team'): away_s = score['score']

                        fixture.home_team_score = int(home_s) if home_s is not None else fixture.home_team_score
                        fixture.away_team_score = int(away_s) if away_s is not None else fixture.away_team_score
                        fixture.last_score_update = timezone.now()

                        if score_item.get('completed', False):
                            fixture.status = FootballFixture.FixtureStatus.FINISHED
                            fixture.save(update_fields=['home_team_score', 'away_team_score', 'status', 'last_score_update'])
                            logger.info(f"[Scores] Fixture {fixture.id} marked as FINISHED by API. Final Score: {home_s}-{away_s}. Triggering settlement.")
                            settle_fixture_pipeline_task.delay(fixture.id)
                        else:
                            fixture.status = FootballFixture.FixtureStatus.LIVE
                            fixture.save(update_fields=['home_team_score', 'away_team_score', 'status', 'last_score_update'])
                            logger.info(f"[Scores] Fixture {fixture.id} is LIVE. Score Updated: {home_s}-{away_s}.")
                except FootballFixture.DoesNotExist:
                    logger.warning(f"[Scores] Received score data for an unknown fixture API ID: {score_item['id']}. Skipping.")

        # --- Time-based Fallback Logic ---
        # Check for any fixtures that we queried but did not get a response for.
        unprocessed_fixtures = fixtures_to_check_qs.exclude(api_id__in=processed_api_ids)

        for fixture in unprocessed_fixtures:
            # If a fixture is past its assumed completion time, mark it as finished.
            if fixture.match_date < assumed_completion_cutoff:
                with transaction.atomic():
                    fixture_to_finish = FootballFixture.objects.select_for_update().get(id=fixture.id)
                    # Double-check status to avoid race conditions
                    if fixture_to_finish.status == FootballFixture.FixtureStatus.FINISHED:
                        continue

                    # If scores are missing, default to 0-0 to allow settlement.
                    if fixture_to_finish.home_team_score is None:
                        fixture_to_finish.home_team_score = 0
                    if fixture_to_finish.away_team_score is None:
                        fixture_to_finish.away_team_score = 0

                    fixture_to_finish.status = FootballFixture.FixtureStatus.FINISHED
                    fixture_to_finish.last_score_update = timezone.now()
                    fixture_to_finish.save(update_fields=['home_team_score', 'away_team_score', 'status', 'last_score_update'])
                    logger.warning(
                        f"[Scores] Fixture {fixture.id} was not in API response and is past assumed completion time. "
                        f"Marking as FINISHED. Score: {fixture_to_finish.home_team_score}-{fixture_to_finish.away_team_score}. Triggering settlement."
                    )
                    settle_fixture_pipeline_task.delay(fixture.id)

    except League.DoesNotExist:
        logger.error(f"[Scores] League {league_id} not found for score update.")
    except TheOddsAPIException as e:
        if e.status_code == 401:
            logger.warning(f"[Scores] API key has insufficient quota. Aborting scores fetch for league {league_id}.")
            return
        logger.exception(f"[Scores] API error fetching scores for league {league_id}: {e}")
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
            logger.error(
                f"Cannot settle outcomes for fixture ID {fixture_id} ({fixture}) because it is marked as FINISHED "
                f"but is missing score data (Home: {fixture.home_team_score}, Away: {fixture.away_team_score}). "
                "This indicates a problem during the score fetching phase. Aborting settlement pipeline for this fixture."
            )
            # Abort the chain for this fixture. The error is logged for visibility.
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
                        if total_score > outcome.point_value: new_status = 'WON'
                        elif total_score == outcome.point_value: new_status = 'PUSH'
                    elif 'under' in outcome.outcome_name.lower():
                        if total_score < outcome.point_value: new_status = 'WON'
                        elif total_score == outcome.point_value: new_status = 'PUSH'
                elif market.api_market_key == 'btts':
                    if ((outcome.outcome_name == 'Yes' and home_score > 0 and away_score > 0) or
                        (outcome.outcome_name == 'No' and not (home_score > 0 and away_score > 0))):
                        new_status = 'WON'
                elif market.api_market_key in ['spreads', 'asian_handicap'] and hasattr(outcome, 'point_value') and outcome.point_value is not None:
                    # Handicap (Spreads) logic
                    point = outcome.point_value
                    if outcome.outcome_name == fixture.home_team.name:
                        # Handicap on home team
                        if home_score + point > away_score:
                            new_status = 'WON'
                        elif home_score + point == away_score:
                            new_status = 'PUSH'
                    elif outcome.outcome_name == fixture.away_team.name:
                        # Handicap on away team
                        if away_score + point > home_score:
                            new_status = 'WON'
                        elif away_score + point == home_score:
                            new_status = 'PUSH'
                elif market.api_market_key in ['exact_score', 'correct_score']:
                    # Correct Score logic
                    try:
                        # Assumes score format is "HomeScore-AwayScore", e.g., "2-1"
                        predicted_scores = outcome.outcome_name.split('-')
                        if len(predicted_scores) == 2:
                            predicted_home = int(predicted_scores[0])
                            predicted_away = int(predicted_scores[1])
                            if home_score == predicted_home and away_score == predicted_away:
                                new_status = 'WON'
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Could not parse correct score outcome '{outcome.outcome_name}' for fixture {fixture.id}: {e}")

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
        bets_to_update = []
        # Iterate over bets that are pending and related to this fixture
        for bet in Bet.objects.filter(
            market_outcome__market__fixture_id=fixture_id, # Updated field name
            status='PENDING'
        ).select_related('market_outcome'):
            # Only update if the outcome has been settled (not PENDING)
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
    """
    Sends a WhatsApp notification to the user about their ticket's status change.
    """
    logger.info(f"Sending settlement notification for BetTicket ID: {ticket_id}, Status: {new_status}")
    try:
        # Correctly fetch the ticket and related user/contact info
        ticket = BetTicket.objects.select_related('user__customer_profile__contact', 'user__wallet').get(pk=ticket_id)
        contact = ticket.user.customer_profile.contact
        
        if new_status == 'WON':
            message_body = (
                f"🎉 Congratulations! Your bet ticket (ID: {ticket.id}) has WON!\n\n"
                f"Amount Won: ${Decimal(winnings):.2f}\n"
                f"Your wallet has been credited. Your new balance is ${ticket.user.wallet.balance:.2f}."
            )
        elif new_status == 'LOST':
            message_body = (
                f"😔 Unfortunately, your bet ticket (ID: {ticket.id}) has lost.\n\n"
                f"Better luck next time! Type 'fixtures' to see upcoming matches."
            )
        else:
            logger.warning(f"send_bet_settlement_notification_task called with unhandled status '{new_status}' for ticket {ticket_id}.")
            return

        # Use the direct utility to send the message
        message_data = create_text_message_data(text_body=message_body)
        send_whatsapp_message(to_phone_number=contact.whatsapp_id, message_type='text', data=message_data)
        logger.info(f"Successfully sent settlement notification to {contact.whatsapp_id} for ticket {ticket_id}.")

    except BetTicket.DoesNotExist:
        logger.error(f"[Notification] BetTicket with ID {ticket_id} not found for sending notification.")
        # Don't retry if the ticket doesn't exist.
    except Exception as e:
        logger.exception(f"[Notification] Error sending notification for ticket {ticket_id}: {e}")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id: int): # No change to signature
    """Settles bet tickets based on bet statuses."""
    if not fixture_id:
        return
    logger.info(f"Settling tickets for fixture ID: {fixture_id}")
    # Find all unique PENDING ticket IDs that contain a bet related to the just-finished fixture.
    try:
        affected_ticket_ids = list(BetTicket.objects.filter(
            status='PENDING',
            bets__market_outcome__market__fixture_id=fixture_id
        ).distinct().values_list('id', flat=True))

        if not affected_ticket_ids:
            logger.info(f"No pending tickets found for fixture {fixture_id} that need settlement checks.")
            return

        # For each affected ticket, trigger the settlement task.
        # The task will handle the full logic of checking if it's ready to be settled.
        # PERFORMANCE FIX: Use chunks to batch process tickets, avoiding a "task storm".
        process_ticket_settlement_batch_task.chunks(zip(affected_ticket_ids), 100).apply_async()

        logger.info(f"Dispatched settlement check tasks for {len(affected_ticket_ids)} tickets related to fixture {fixture_id} in batches of 100.")
    except Exception as e:
        logger.exception(f"Error settling tickets for fixture {fixture_id}")
        raise self.retry(exc=e)
