import logging
from django.conf import settings
from celery import chord, shared_task, chain, group
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
# List of additional markets to fetch alongside the default ones.
ADDITIONAL_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_ADDITIONAL_MARKETS', "alternate_totals,btts")
PREFERRED_ODDS_API_BOOKMAKERS = getattr(settings, 'THE_ODDS_API_PREFERRED_BOOKMAKERS', "bet365,pinnacle,unibet,williamhill,betfair")
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
    """Fetches scores for a league and updates fixture statuses (Live/Finished)."""
    logger.info(f"Fetching scores for league ID: {league_id}")
    now = timezone.now()
    # We only check for scores on scheduled matches that started recently
    # to avoid checking very old, stuck fixtures.
    assumed_end_time_cutoff = now - timedelta(minutes=ASSUMED_COMPLETION_MINUTES)
    try:
        league = League.objects.get(id=league_id)
        fixtures_to_check = FootballFixture.objects.filter(
            league=league
        ).filter(
            # Condition 1: The fixture is already marked as LIVE.
            models.Q(status=FootballFixture.FixtureStatus.LIVE) |
            # Condition 2: The fixture is SCHEDULED, its start time is in the past,
            # but not so far in the past that it's definitely over.
            models.Q(
                status=FootballFixture.FixtureStatus.SCHEDULED,
                match_date__lt=now, # It should have started
                match_date__gt=assumed_end_time_cutoff # But it started recently enough to still be in-play
            )
        ).values_list('api_id', flat=True)

        if not fixtures_to_check.exists():
            logger.info(f"No fixtures need a score update for league ID: {league_id}.")
            return

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=list(fixtures_to_check))
        if not scores_data:
            logger.info(f"The Odds API returned no score data for the {fixtures_to_check.count()} fixtures checked in league {league_id}.")
            return
        
        for score_item in scores_data:
            with transaction.atomic():
                fixture = FootballFixture.objects.select_for_update().get(api_id=score_item['id'])
                if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                    continue

                logger.info(f"Processing score for fixture {fixture.api_id}, current status: {fixture.status}")
                logger.info(f"API commence_time: {score_item.get('commence_time')}, fixture match_date: {fixture.match_date}, now: {now}")


                if score_item.get('completed', False):
                    # Use the team names from the score item itself for robust matching
                    home_s, away_s = None, None
                    api_home_team_name = score_item.get('home_team')
                    api_away_team_name = score_item.get('away_team')

                    if score_item.get('scores') and api_home_team_name and api_away_team_name:
                        for score in score_item['scores']:
                            if score['name'] == api_home_team_name:
                                home_s = score['score']
                            elif score['name'] == api_away_team_name:
                                away_s = score['score']
                    else:
                        logger.warning(
                            f"Score data for fixture {fixture.api_id} is missing 'scores' array or team names. "
                            f"API Response (snippet): {str(score_item)[:200]}"
                        )

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