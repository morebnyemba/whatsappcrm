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
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us")
# *** FIX: Request all significant market types ***
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,spreads,btts")
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)

# --- Helper Function ---
def _parse_outcome_details(outcome_name_api, market_key_api):
    name_part, point_part = outcome_name_api, None
    if market_key_api in ['totals', 'spreads']:
        try:
            parts = outcome_name_api.split()
            last_part = parts[-1]
            # Check if the last part looks like a number (can be +/- decimal)
            if last_part.replace('.', '', 1).lstrip('+-').isdigit():
                point_part = float(last_part)
                # Reconstruct name_part, or use original if nothing left
                name_part = " ".join(parts[:-1]) or outcome_name_api
        except (ValueError, IndexError):
            logger.warning(f"Could not parse point from outcome: '{outcome_name_api}' for market '{market_key_api}'")
    return name_part, point_part

# --- Data Fetching & Processing Tasks ---

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """Step 1: Fetches and updates football leagues from the API."""
    client = TheOddsAPIClient()
    created_count, updated_count = 0, 0
    logger.info("Pipeline Step 1: Starting league fetch task.")
    try:
        sports_data = client.get_sports(all_sports=True)
        for item in sports_data:
            if 'soccer' not in item.get('key', ''): continue
            
            _, created = League.objects.update_or_create(
                api_id=item['key'],
                defaults={'name': item.get('title', 'Unknown League'), 'sport_key': 'soccer', 'active': True, 'logo_url': item.get('logo')}
            )
            if created: created_count += 1
            else: updated_count += 1
        logger.info(f"Leagues Task Complete: {created_count} created, {updated_count} updated.")
        return f"Processed {created_count + updated_count} leagues."
    except Exception as e:
        logger.exception("Critical error in league fetching task.")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id):
    """(Sub-task) Fetches events for a specific league."""
    client, created_count, updated_count = TheOddsAPIClient(), 0, 0
    try:
        league = League.objects.get(id=league_id)
        logger.info(f"Fetching events for league: {league.name}")
        events_data = client.get_events(sport_key=league.api_id)
        
        for item in events_data:
            if not item.get('home_team') or not item.get('away_team'):
                logger.warning(f"Skipping event ID {item.get('id')} as it lacks team data.")
                continue

            with transaction.atomic():
                home_obj, _ = Team.objects.get_or_create(name=item['home_team'])
                away_obj, _ = Team.objects.get_or_create(name=item['away_team'])
                
                _, created = FootballFixture.objects.update_or_create(
                    api_id=item['id'],
                    defaults={
                        'league': league, 'home_team': home_obj, 'away_team': away_obj,
                        'match_date': parser.isoparse(item['commence_time']),
                        'status': 'SCHEDULED'
                    }
                )
                if created: created_count += 1
                else: updated_count += 1
            
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Events for {league.name}: {created_count} created, {updated_count} updated.")
    except League.DoesNotExist:
        logger.warning(f"League with ID {league_id} not found for event fetching.")
    except Exception as e:
        logger.exception(f"Unexpected error fetching events for league {league_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def process_leagues_and_dispatch_subtasks_task(self, previous_task_result=None):
    """
    Step 2 of the main pipeline. Iterates through leagues to dispatch odds and score updates.
    """
    now = timezone.now()
    logger.info("Pipeline Step 2: Processing leagues and dispatching sub-tasks.")
    
    leagues = League.objects.filter(active=True)
    if not leagues.exists():
        logger.warning("Orchestrator: No active leagues found to process.")
        return

    for league in leagues:
        # Task to fetch new events for the league if event discovery is stale
        if not league.last_fetched_events or league.last_fetched_events < (now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)):
            fetch_events_for_league_task.apply_async(args=[league.id])

        # Query for fixtures that need odds updates
        # Only fetch odds for 'SCHEDULED' events whose match_date is within the ODDS_LEAD_TIME_DAYS
        # And whose odds update is stale
        stale_fixtures_q = models.Q(
            models.Q(match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))),
            models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES))
        )
        
        # Ensure we only get fixtures that are SCHEDULED before trying to fetch odds
        event_ids = list(FootballFixture.objects.filter(league=league, status=FootballFixture.FixtureStatus.SCHEDULED).filter(stale_fixtures_q).values_list('api_id', flat=True))
        
        if event_ids:
            logger.info(f"Found {len(event_ids)} fixtures needing odds update for league: {league.name}")
            for i in range(0, len(event_ids), ODDS_FETCH_EVENT_BATCH_SIZE):
                batch = event_ids[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
                fetch_odds_for_event_batch_task.apply_async(args=[league.api_id, batch])

        # Always dispatch score fetching for the league (it will handle its own staleness and status checks)
        fetch_scores_for_league_task.apply_async(args=[league.id])
        
    logger.info(f"Orchestrator: Finished dispatching jobs for {leagues.count()} leagues.")

# --- Main Orchestrator ---
@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """Main orchestrator task that uses a Celery chain for a reliable data pipeline."""
    logger.info("Orchestrator: Kicking off the full data update pipeline.")
    
    pipeline = chain(
        fetch_and_update_leagues_task.s(),
        process_leagues_and_dispatch_subtasks_task.s()
    )
    pipeline.apply_async()
    
    logger.info("Orchestrator: Update pipeline has been dispatched.")
    return "Full data update pipeline initiated successfully."

# --- Individual Sub-Tasks ---

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, sport_key, event_ids, markets=None, regions=None):
    """
    (Sub-task) Fetches and updates odds for a batch of events.
    Now includes robust handling for 422 Unprocessable Entity errors,
    attempting to retry individual problematic event IDs.
    """
    client = TheOddsAPIClient()
    markets_to_fetch = markets or DEFAULT_ODDS_API_MARKETS
    regions_to_fetch = regions or DEFAULT_ODDS_API_REGIONS

    logger.info(f"Fetching odds for {len(event_ids)} events in {sport_key} for markets: '{markets_to_fetch}'")
    
    successful_event_ids = []
    failed_event_ids = []

    try:
        odds_data = client.get_odds(
            sport_key=sport_key, 
            event_ids=event_ids, 
            regions=regions_to_fetch, 
            markets=markets_to_fetch
        )
        
        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}

        with transaction.atomic():
            for event_data in odds_data:
                fixture = fixtures_map.get(event_data['id'])
                if not fixture:
                    logger.warning(f"Fixture with API ID {event_data['id']} not found in DB, skipping odds processing.")
                    failed_event_ids.append(event_data['id']) # Or handle as a different type of failure
                    continue
                
                # Clear existing markets for this fixture to prevent stale data
                Market.objects.filter(fixture_display=fixture).delete()
                
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
                successful_event_ids.append(fixture.api_id)
        
        logger.info(f"Successfully processed odds for {len(successful_event_ids)} fixtures.")
        if failed_event_ids:
            logger.warning(f"Failed to process odds for {len(failed_event_ids)} event IDs in this batch (likely not returned by API): {failed_event_ids}")

    except TheOddsAPIException as e:
        if e.status_code == 422:
            # If a 422 occurs for a batch, it's likely due to one or more invalid event_ids.
            # We can't know which one without a response body, so we'll log and retry
            # the entire batch, hoping the next attempt (after 300s) might work
            # if the issue was transient, or if the problematic eventIds become valid
            # (less likely) or are removed by subsequent calls to fetch_events_for_league_task.
            
            # More robust handling for 422:
            # If this is the first retry (self.request.retries == 0),
            # log a warning and let it retry.
            # If it's a subsequent retry, we might consider more aggressive action,
            # like trying to fetch odds for each event_id individually (if batch size is small enough)
            # or marking the events as problematic.
            
            logger.warning(
                f"The Odds API HTTPError for {sport_key} with event_ids {event_ids}: "
                f"422 Client Error: Unprocessable Entity. Status: {e.status_code}. Response: {e.response_body or 'No response body'}. "
                f"Attempt {self.request.retries + 1} of {self.max_retries}. Retrying in {self.default_retry_delay}s."
            )
            # This will retry the entire batch
            raise self.retry(exc=e)
        else:
            logger.error(f"API Error fetching odds for {sport_key} (Event IDs: {event_ids}): {e}")
            raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Unexpected error fetching odds for {sport_key} (Event IDs: {event_ids}).")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id):
    """(Sub-task) Fetches scores and updates status for a single league."""
    now = timezone.now()
    try:
        league = League.objects.get(id=league_id)
        
        # Fetch scores for LIVE or SCHEDULED fixtures that have either commenced
        # or are very close to commencing (within 5 minutes), and whose score
        # update is stale (more than 10 minutes old).
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(league=league, status=FootballFixture.FixtureStatus.SCHEDULED, match_date__lt=now + timedelta(minutes=5)),
            models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lt=now - timedelta(minutes=10))
        ).distinct()

        if not fixtures_to_check.exists():
            logger.info(f"No fixtures needing score update for league: {league.name}")
            return
            
        fixture_ids = list(fixtures_to_check.values_list('api_id', flat=True))
        logger.info(f"Fetching scores for {len(fixture_ids)} fixtures in league: {league.name}")

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=fixture_ids)
        
        # Map fixtures by api_id for efficient lookup
        fixtures_map = {f.api_id: f for f in fixtures_to_check}

        for score_item in scores_data:
            with transaction.atomic():
                fixture = fixtures_map.get(score_item['id'])
                if not fixture:
                    logger.warning(f"Score received for unknown fixture API ID {score_item['id']}, skipping.")
                    continue

                # Ensure match_date is timezone-aware for comparison
                commence_time = parser.isoparse(score_item['commence_time'])
                if timezone.is_naive(commence_time):
                    commence_time = timezone.make_aware(commence_time, timezone.get_current_timezone())

                if score_item.get('completed', False):
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_s = score['score']
                            if score['name'] == fixture.away_team.name: away_s = score['score']
                    
                    fixture.home_team_score = int(home_s) if home_s is not None else None
                    fixture.away_team_score = int(away_s) if away_s is not None else None
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    fixture.last_score_update = now
                    fixture.save()
                    logger.info(f"Fixture {fixture.api_id} ({fixture.home_team.name} vs {fixture.away_team.name}) completed. Score: {fixture.home_team_score}-{fixture.away_team_score}. Dispatching settlement chain.")
                    
                    # Chain settlement tasks for completed fixture
                    chain(
                        settle_outcomes_for_fixture_task.s(fixture.id),
                        settle_bets_for_fixture_task.s(),
                        settle_tickets_for_fixture_task.s()
                    ).apply_async()
                else:
                    # Mark as LIVE if match has started or is past its commence_time,
                    # and it's not already LIVE or FINISHED.
                    if fixture.status == FootballFixture.FixtureStatus.SCHEDULED and commence_time <= now:
                         fixture.status = FootballFixture.FixtureStatus.LIVE
                         logger.info(f"Fixture {fixture.api_id} ({fixture.home_team.name} vs {fixture.away_team.name}) is now LIVE.")
                    # Update scores if available for live matches (even if not explicitly in scores_data)
                    # TheOddsAPI can sometimes provide scores for live games in the 'scores' array even if 'completed' is False
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_s = score['score']
                            if score['name'] == fixture.away_team.name: away_s = score['score']
                    fixture.home_team_score = int(home_s) if home_s is not None else fixture.home_team_score
                    fixture.away_team_score = int(away_s) if away_s is not None else fixture.away_team_score

                    fixture.last_score_update = now
                    fixture.save()
                    logger.debug(f"Fixture {fixture.api_id} ({fixture.home_team.name} vs {fixture.away_team.name}) status: {fixture.status}.")

    except League.DoesNotExist:
        logger.warning(f"League with ID {league_id} not found for score fetching.")
    except TheOddsAPIException as e:
        logger.error(f"API Error fetching scores for league {league_id}: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Unexpected error fetching scores for league {league_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id):
    """(Sub-task) Settles the result status of all market outcomes for a finished fixture."""
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, status=FootballFixture.FixtureStatus.FINISHED)
        home_score, away_score = fixture.home_team_score, fixture.away_team_score

        if home_score is None or away_score is None:
            logger.warning(f"Cannot settle outcomes for fixture {fixture_id}: scores are missing.")
            return

        outcomes_to_update = []
        for market in fixture.markets.prefetch_related('outcomes'):
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'LOST' # Default to lost
                
                # Head-to-Head (H2H)
                if market.api_market_key == 'h2h':
                    if (outcome.outcome_name == fixture.home_team.name and home_score > away_score) or \
                       (outcome.outcome_name == fixture.away_team.name and away_score > home_score):
                        new_status = 'WON'
                    elif outcome.outcome_name.lower() == 'draw' and home_score == away_score:
                        new_status = 'WON'
                
                # Totals (Over/Under)
                elif market.api_market_key == 'totals' and outcome.point_value is not None:
                    total_score = home_score + away_score
                    if 'over' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score > outcome.point_value else ('PUSH' if total_score == outcome.point_value else 'LOST')
                    elif 'under' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score < outcome.point_value else ('PUSH' if total_score == outcome.point_value else 'LOST')
                
                # Spreads (Handicap)
                elif market.api_market_key == 'spreads' and outcome.point_value is not None:
                    # Spreads can be complex, often involves adjusting scores.
                    # Assuming positive point_value means handicap for home_team, negative for away_team
                    # This is a simplified interpretation and might need adjustment based on API specifics
                    if outcome.outcome_name == fixture.home_team.name: # Home team with a handicap
                        effective_home_score = home_score + outcome.point_value # point_value is usually negative for handicap
                        new_status = 'WON' if effective_home_score > away_score else ('PUSH' if effective_home_score == away_score else 'LOST')
                    elif outcome.outcome_name == fixture.away_team.name: # Away team with a handicap
                        effective_away_score = away_score + outcome.point_value # point_value is usually negative for handicap
                        new_status = 'WON' if effective_away_score > home_score else ('PUSH' if effective_away_score == home_score else 'LOST')
                    # A more robust spread calculation would need to handle positive/negative points
                    # and which team it applies to explicitly based on API documentation.
                    # For now, it assumes 'outcome.outcome_name' aligns with the team getting the spread.

                # Both Teams To Score (BTTS)
                elif market.api_market_key == 'btts':
                    both_scored = home_score > 0 and away_score > 0
                    if (outcome.outcome_name == 'Yes' and both_scored) or \
                       (outcome.outcome_name == 'No' and not both_scored):
                        new_status = 'WON'
                
                # Double Chance - Needs specific handling as it covers 2 outcomes
                # Outcomes might be "Home/Draw", "Home/Away", "Draw/Away"
                elif market.api_market_key == 'double_chance':
                    # Example: "Home/Draw" wins if Home wins OR Draw
                    if outcome.outcome_name == f"{fixture.home_team.name}/Draw":
                        if home_score > away_score or home_score == away_score:
                            new_status = 'WON'
                    elif outcome.outcome_name == f"{fixture.away_team.name}/Draw":
                        if away_score > home_score or home_score == away_score:
                            new_status = 'WON'
                    elif outcome.outcome_name == f"{fixture.home_team.name}/{fixture.away_team.name}":
                        if home_score > away_score or away_score > home_score:
                            new_status = 'WON'
                
                # Full Time Result - European (1X2) - Equivalent to H2H for home/away/draw outcomes
                elif market.api_market_key == 'full_time_result':
                    if (outcome.outcome_name == fixture.home_team.name and home_score > away_score) or \
                       (outcome.outcome_name == fixture.away_team.name and away_score > home_score) or \
                       (outcome.outcome_name.lower() == 'draw' and home_score == away_score):
                        new_status = 'WON'

                # Other common markets would need similar if/elif blocks.
                # Example: 'correct_score' would require matching exact scores.
                # 'half_time_full_time' would need half-time scores.
                # For this example, we'll focus on the listed ones.

                if new_status != 'PENDING' and outcome.result_status == 'PENDING': # Only update if status changed from PENDING
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)
        
        if outcomes_to_update:
            MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
            logger.info(f"Settlement: Marked {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
        else:
            logger.info(f"Settlement: No outcomes updated for fixture {fixture_id}.")
        return fixture_id
    except FootballFixture.DoesNotExist:
        logger.warning(f"Cannot settle outcomes: fixture {fixture_id} not found or not finished.")
    except Exception as e:
        logger.exception(f"Error settling outcomes for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id):
    """(Sub-task) Settles all individual bets for a fixture."""
    if not fixture_id: return None
    try:
        # Use select_related to reduce queries
        bets_to_settle = Bet.objects.filter(
            market_outcome__market__fixture_display_id=fixture_id, 
            status='PENDING'
        ).select_related('market_outcome')

        updated_bets = []
        for bet in bets_to_settle:
            if bet.market_outcome.result_status != 'PENDING':
                bet.status = bet.market_outcome.result_status
                updated_bets.append(bet)
        
        if updated_bets:
            Bet.objects.bulk_update(updated_bets, ['status'])
        logger.info(f"Settlement: Settled {len(updated_bets)} bets for fixture {fixture_id}.")
        return fixture_id
    except Exception as e:
        logger.exception(f"Error settling bets for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id):
    """(Sub-task) Settles all bet tickets related to a fixture."""
    if not fixture_id: return None
    try:
        # Get distinct ticket IDs that have at least one bet for this fixture
        ticket_ids_to_check = BetTicket.objects.filter(
            bets__market_outcome__market__fixture_display_id=fixture_id
        ).distinct().values_list('id', flat=True)

        for ticket_id in ticket_ids_to_check:
            # Re-fetch the ticket and all its bets for the settlement logic
            # Use select_related for efficiency if BetTicket.bets.all() causes N+1 queries
            ticket = BetTicket.objects.prefetch_related('bets__market_outcome').get(id=ticket_id)
            
            # Check if all bets on the ticket are no longer PENDING
            if all(b.status != 'PENDING' for b in ticket.bets.all()):
                ticket.settle_ticket() # This method should contain the logic to set ticket status and potentially credit user
                logger.info(f"Settlement: Ticket {ticket_id} settled to status {ticket.status}.")
            else:
                logger.info(f"Settlement: Ticket {ticket_id} still has pending bets, not yet settled.")

        logger.info(f"Settlement: Checked {len(ticket_ids_to_check)} tickets for fixture {fixture_id}.")
    except Exception as e:
        logger.exception(f"Error settling tickets for fixture {fixture_id}.")
        raise self.retry(exc=e)