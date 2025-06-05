# football_data_app/tasks.py
import logging
from celery import shared_task, group
from django.db import transaction, IntegrityError, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta

from whatsappcrm_backend import settings

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

DEFAULT_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "eu,uk")
DEFAULT_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,spreads")
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
DAYS_FROM_FOR_SCORES = getattr(settings, 'THE_ODDS_API_DAYS_FROM_SCORES', 3)
# How long before commencement to start fetching odds more frequently
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 2)
# How frequently to update odds for upcoming (but not immediate) events
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
# How frequently to update odds for imminently starting events
ODDS_IMMINENT_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_IMMINENT_STALENESS_MINUTES', 15)
# How long after an event starts should we still try to fetch its initial odds if missed
ODDS_POST_COMMENCEMENT_GRACE_HOURS = getattr(settings, 'THE_ODDS_API_POST_COMMENCEMENT_GRACE_HOURS', 1)


# --- Helper Function for Parsing Outcome Details ---
def parse_outcome_details(outcome_name_api, market_key_api):
    name_part = outcome_name_api
    point_part = None
    # Enhanced parsing for common cases
    if market_key_api in ['totals', 'h2h_spread'] or 'spreads' in market_key_api: # 'h2h_spread' for some APIs, or just 'spreads'
        try:
            parts = outcome_name_api.split()
            if len(parts) > 0: # Check if parts is not empty
                # Try to extract a number from the last part
                potential_point_str = parts[-1]
                # More robust check for numeric value, including negative and decimal
                if potential_point_str.replace('.', '', 1).lstrip('+-').isdigit():
                    point_part = float(potential_point_str)
                    # If the point was extracted, the name is the rest
                    if len(parts) > 1:
                        name_part = " ".join(parts[:-1])
                    else: # If only number was there (e.g. outcome "2.5" for a total), keep it as name for now or decide default
                        name_part = outcome_name_api # Or potentially just "Total" if context allows
                # Handle cases like "Over" or "Under" where point is implicit from market parameter (not handled here directly)
                elif parts[0].lower() in ['over', 'under'] and len(parts) > 1: # e.g. "Over 2.5"
                    # This logic can be tricky if point is sometimes in name, sometimes not
                    # This function assumes point is explicitly in the name if market type suggests it
                    pass # Keep as is, let point_part be None if not clearly parseable with a number

        except ValueError:
            logger.warning(f"Could not parse point from outcome: {outcome_name_api} for market {market_key_api}")
            name_part = outcome_name_api # Fallback
            point_part = None
    return name_part, point_part


# --- Bet Settlement Task ---
@shared_task(bind=True, max_retries=3, default_retry_delay=10 * 60) # Retry every 10 mins
def settle_bets_for_fixture_task(self, fixture_id):
    """
    Settles bets (MarketOutcomes) for a given completed fixture with scores.
    This is a placeholder and needs specific logic based on market types.
    """
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, completed=True, home_team_score__isnull=False, away_team_score__isnull=False)
        logger.info(f"Task started: settle_bets_for_fixture_task for Fixture ID: {fixture_id}")

        home_score = fixture.home_team_score
        away_score = fixture.away_team_score

        outcomes_to_update = []

        for market in fixture.markets.all():
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'PENDING' # Default
                # --- H2H (Match Winner) ---
                if market.api_market_key == 'h2h': # Assuming 'h2h' is moneyline/match winner
                    if outcome.outcome_name == fixture.home_team_name: # Bet on Home
                        if home_score > away_score: new_status = 'WON'
                        else: new_status = 'LOST'
                    elif outcome.outcome_name == fixture.away_team_name: # Bet on Away
                        if away_score > home_score: new_status = 'WON'
                        else: new_status = 'LOST'
                    elif outcome.outcome_name.lower() == 'draw': # Bet on Draw
                        if home_score == away_score: new_status = 'WON'
                        else: new_status = 'LOST'
                
                # --- Totals (Over/Under) ---
                elif market.api_market_key == 'totals':
                    total_score = home_score + away_score
                    if outcome.point_value is not None: # Expecting point_value to be set (e.g., 2.5)
                        if 'over' in outcome.outcome_name.lower():
                            if total_score > outcome.point_value: new_status = 'WON'
                            elif total_score == outcome.point_value: new_status = 'PUSH' # Or VOID depending on bookie rules
                            else: new_status = 'LOST'
                        elif 'under' in outcome.outcome_name.lower():
                            if total_score < outcome.point_value: new_status = 'WON'
                            elif total_score == outcome.point_value: new_status = 'PUSH'
                            else: new_status = 'LOST'
                
                # --- Spreads (Handicap) ---
                # Example for Asian Handicap or Point Spread. Logic can be complex.
                # outcome.outcome_name might be "Team A", outcome.point_value might be -1.5
                # outcome.outcome_name might be "Team B", outcome.point_value might be +1.5
                elif market.api_market_key in ['spreads', 'h2h_spread']:
                    if outcome.point_value is not None:
                        # Assuming outcome_name is the team name for spreads
                        if outcome.outcome_name == fixture.home_team_name: # Bet on Home Team with spread
                            if (home_score + outcome.point_value) > away_score: new_status = 'WON'
                            elif (home_score + outcome.point_value) == away_score: new_status = 'PUSH' # Or HALF_WON/LOST for .25/.75 lines
                            else: new_status = 'LOST'
                        elif outcome.outcome_name == fixture.away_team_name: # Bet on Away Team with spread
                            if (away_score + outcome.point_value) > home_score: new_status = 'WON'
                            elif (away_score + outcome.point_value) == home_score: new_status = 'PUSH'
                            else: new_status = 'LOST'
                
                # Add more market types (e.g., Correct Score, Both Teams to Score)
                
                if new_status != 'PENDING' and new_status != outcome.result_status :
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)

        if outcomes_to_update:
            with transaction.atomic():
                MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
            logger.info(f"Settled {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
        else:
            logger.info(f"No pending outcomes found or no status changes for fixture {fixture_id}.")

        return f"Bet settlement attempt complete for fixture {fixture_id}. Updated: {len(outcomes_to_update)}."

    except FootballFixture.DoesNotExist:
        logger.warning(f"Fixture ID {fixture_id} not found or not ready for settlement. Skipping.")
        return f"Fixture {fixture_id} not ready/found."
    except Exception as e:
        logger.exception(f"Unexpected error in settle_bets_for_fixture_task for fixture ID {fixture_id}: {e}")
        raise self.retry(exc=e)


# --- Core Data Fetching Tasks (Updated with minor fixes and settings usage) ---

@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60)
def fetch_and_update_sports_leagues_task(self):
    client = TheOddsAPIClient()
    try:
        logger.info("Task started: fetch_and_update_sports_leagues_task")
        sports_data = client.get_sports(all_sports=True)

        if not sports_data:
            logger.warning("No sports data received from API.")
            return "No sports data received."

        updated_count = 0
        created_count = 0
        for sport_item in sports_data:
            sport_key = sport_item.get('key')
            sport_title = sport_item.get('title')
            active_api = sport_item.get('active', True)

            if not sport_key or not sport_title:
                logger.warning(f"Skipping sport item due to missing key or title: {sport_item}")
                continue

            with transaction.atomic():
                league, created = League.objects.update_or_create(
                    sport_key=sport_key,
                    defaults={
                        'name': sport_title,
                        'sport_title': sport_title,
                        'active': active_api,
                    }
                )
                if created: created_count +=1
                else: updated_count +=1
        
        logger.info(f"Task finished: fetch_and_update_sports_leagues_task. Created: {created_count}, Updated: {updated_count}.")
        return f"Sports/Leagues update complete. Created: {created_count}, Updated: {updated_count}."

    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_and_update_sports_leagues_task: {e.status_code} - {e}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None:
            raise self.retry(exc=e)
        return f"Failed due to API error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in fetch_and_update_sports_leagues_task.")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=10 * 60)
def fetch_events_for_league_task(self, league_id):
    """Fetches upcoming events (fixtures) for a specific active league using the /events endpoint."""
    try:
        league = League.objects.get(id=league_id, active=True)
    except League.DoesNotExist:
        logger.warning(f"League with ID {league_id} not found or not active. Skipping event fetch.")
        return f"League {league_id} not found or inactive."

    client = TheOddsAPIClient()
    try:
        logger.info(f"Task started: fetch_events_for_league_task for League: {league.sport_key}")
        # For /events, it's usually about discovering IDs. Fetching specific dates might be better via /odds with commenceTimeTo/From
        events_data = client.get_events(sport_key=league.sport_key) # This fetches all known events, might be large

        if not events_data:
            logger.info(f"No events data received for league {league.sport_key} from /events endpoint.")
            league.last_fetched_events = timezone.now()
            league.save()
            return f"No events data for {league.sport_key} via /events."

        created_count = 0
        updated_count = 0
        
        for event_item in events_data:
            event_api_id = event_item.get('id')
            commence_time_str = event_item.get('commence_time')
            home_team_name = event_item.get('home_team')
            away_team_name = event_item.get('away_team')
            sport_key_api = event_item.get('sport_key')

            if not all([event_api_id, commence_time_str, home_team_name, away_team_name, sport_key_api]):
                logger.warning(f"Skipping event item from /events due to missing core data: {event_item} for league {league.sport_key}")
                continue
            
            try:
                commence_time = parser.isoparse(commence_time_str)
            except ValueError:
                logger.error(f"Could not parse commence_time '{commence_time_str}' from /events for event {event_api_id}. Skipping.")
                continue

            with transaction.atomic():
                # Link teams
                home_team_obj = Team.get_or_create_team(home_team_name)
                away_team_obj = Team.get_or_create_team(away_team_name)

                fixture, created = FootballFixture.objects.update_or_create(
                    event_api_id=event_api_id,
                    defaults={
                        'league': league,
                        'sport_key': sport_key_api,
                        'commence_time': commence_time,
                        'home_team_name': home_team_name,
                        'away_team_name': away_team_name,
                        'home_team': home_team_obj,
                        'away_team': away_team_obj,
                        'completed': event_item.get('completed', False),
                    }
                )
                if created: created_count += 1
                else: updated_count += 1
        
        league.last_fetched_events = timezone.now()
        league.save()
        
        logger.info(f"Task finished: fetch_events_for_league_task for {league.sport_key}. Processed from /events: {created_count+updated_count} (C:{created_count}, U:{updated_count}).")
        return f"Events update from /events complete for {league.sport_key}."

    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_events_for_league_task for {league.sport_key}: {e.status_code} - {e}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None:
            raise self.retry(exc=e)
        return f"Failed for {league.sport_key} due to API error: {e}"
    except Exception as e:
        logger.exception(f"Unexpected error in fetch_events_for_league_task for {league.sport_key}.")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=3 * 60)
def fetch_odds_for_events_task(self, sport_key, event_ids_list, regions=DEFAULT_REGIONS, markets=DEFAULT_MARKETS):
    if not event_ids_list:
        logger.info(f"No event_ids provided for odds fetch (sport {sport_key}). Skipping.")
        return "No event_ids provided."

    client = TheOddsAPIClient()
    try:
        logger.info(f"Task started: fetch_odds_for_events_task for sport {sport_key}, {len(event_ids_list)} events.")
        odds_data_list = client.get_odds(
            sport_key=sport_key, regions=regions, markets=markets, event_ids=event_ids_list
        )

        if not odds_data_list: # API returned empty list for the given event_ids
            logger.info(f"No odds data received from API for sport {sport_key}, events: {','.join(event_ids_list)}.")
            FootballFixture.objects.filter(event_api_id__in=event_ids_list, sport_key=sport_key).update(last_odds_update=timezone.now())
            return "No odds data received for specified events."

        processed_event_ids = set()
        for event_data_from_api in odds_data_list:
            event_api_id = event_data_from_api.get("id")
            home_team_name_api = event_data_from_api.get("home_team")
            away_team_name_api = event_data_from_api.get("away_team")
            commence_time_api_str = event_data_from_api.get("commence_time")

            if not all([event_api_id, home_team_name_api, away_team_name_api, commence_time_api_str]):
                logger.warning(f"Odds data for an event missing core fields (id, teams, commence_time): {event_data_from_api}. Skipping.")
                continue
            
            processed_event_ids.add(event_api_id)
            try:
                commence_time_api = parser.isoparse(commence_time_api_str)
                
                # Get or Create Fixture - /odds endpoint is often the source of truth for events too
                # Ensure league exists
                league_obj, _ = League.objects.get_or_create(sport_key=sport_key, defaults={'name': event_data_from_api.get('sport_title', sport_key.replace("_"," ").title())})
                
                # Link teams
                home_team_obj = Team.get_or_create_team(home_team_name_api)
                away_team_obj = Team.get_or_create_team(away_team_name_api)

                fixture, created = FootballFixture.objects.update_or_create(
                    event_api_id=event_api_id,
                    defaults={
                        'league': league_obj,
                        'sport_key': sport_key, # sport_key from the request
                        'home_team_name': home_team_name_api,
                        'away_team_name': away_team_name_api,
                        'home_team': home_team_obj,
                        'away_team': away_team_obj,
                        'commence_time': commence_time_api,
                    }
                )
                if created:
                    logger.info(f"Fixture {event_api_id} created while processing odds.")
                
                with transaction.atomic():
                    Market.objects.filter(fixture_display=fixture).delete() # Clear old markets/outcomes

                    for bookmaker_data in event_data_from_api.get("bookmakers", []):
                        bookmaker_key = bookmaker_data.get("key")
                        bookmaker_title = bookmaker_data.get("title")
                        if not bookmaker_key or not bookmaker_title: continue

                        bookie, _ = Bookmaker.objects.update_or_create(
                            api_bookmaker_key=bookmaker_key, defaults={'name': bookmaker_title}
                        )

                        for market_data in bookmaker_data.get("markets", []):
                            market_key_api = market_data.get("key")
                            market_last_update_str = market_data.get("last_update")
                            if not market_key_api or not market_last_update_str: continue
                            
                            market_api_last_update_dt = parser.isoparse(market_last_update_str)
                            category_name = market_key_api.replace("_", " ").title()
                            market_category, _ = MarketCategory.objects.get_or_create(name=category_name)

                            market_instance, _ = Market.objects.create( # Using create since old ones deleted
                                fixture_display=fixture, bookmaker=bookie, api_market_key=market_key_api,
                                category=market_category, last_updated_odds_api=market_api_last_update_dt
                            )
                            
                            for outcome_data in market_data.get("outcomes", []):
                                outcome_name_api = outcome_data.get("name")
                                outcome_price = outcome_data.get("price")
                                if outcome_name_api is None or outcome_price is None: continue
                                odds_decimal = float(outcome_price)
                                parsed_name, parsed_point = parse_outcome_details(outcome_name_api, market_key_api)

                                MarketOutcome.objects.create(
                                    market=market_instance, outcome_name=parsed_name,
                                    odds=odds_decimal, point_value=parsed_point
                                )
                    fixture.last_odds_update = timezone.now()
                    fixture.save()
                    logger.info(f"Successfully processed odds for event {event_api_id}")

            except IntegrityError as e:
                logger.error(f"Database integrity error processing odds for event {event_api_id}: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error processing odds for event {event_api_id}: {e}")
        
        unprocessed_event_ids = set(event_ids_list) - processed_event_ids
        if unprocessed_event_ids:
            FootballFixture.objects.filter(event_api_id__in=list(unprocessed_event_ids), sport_key=sport_key).update(last_odds_update=timezone.now())
            logger.info(f"Marked {len(unprocessed_event_ids)} events as checked for odds (no data returned): {','.join(list(unprocessed_event_ids))}")

        logger.info(f"Task finished: fetch_odds_for_events_task for sport {sport_key}. Processed {len(processed_event_ids)} events from API response.")
        return f"Odds update complete for {len(processed_event_ids)} events in sport {sport_key}."

    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_odds_for_events_task for sport {sport_key}: {e.status_code} - {e}")
        # Retry logic is crucial here
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None and not isinstance(e.response_text, str) and "API key" not in str(e): # Avoid retrying auth errors unless it's a temporary glitch
            raise self.retry(exc=e)
        # For non-retryable API errors (like bad event ID format, though client should prevent this), log and don't retry.
        FootballFixture.objects.filter(event_api_id__in=event_ids_list, sport_key=sport_key).update(last_odds_update=timezone.now()) # Mark as checked to avoid loop
        return f"Failed for {sport_key} due to non-retryable API error or max retries: {e}"
    except Exception as e:
        logger.exception(f"Unexpected error in fetch_odds_for_events_task for sport {sport_key}.")
        raise self.retry(exc=e) # Retry for other unexpected errors


@shared_task(bind=True, max_retries=2, default_retry_delay=15 * 60)
def fetch_scores_for_league_events_task(self, league_id):
    try:
        league = League.objects.get(id=league_id, active=True)
    except League.DoesNotExist:
        logger.warning(f"League {league_id} not found or inactive for score fetching.")
        return f"League {league_id} not found/inactive."

    client = TheOddsAPIClient()
    try:
        logger.info(f"Task started: fetch_scores_for_league_events_task for League: {league.sport_key}")
        
        now = timezone.now()
        # Look for events that (a) started up to DAYS_FROM_FOR_SCORES days ago and are not marked completed,
        # OR (b) completed recently but might need score verification or settlement.
        # OR (c) are live (started recently, not completed).
        # This logic aims to catch games that need score updates.
        
        # Fetch events that commenced between DAYS_FROM_FOR_SCORES ago and a bit into the future (for live games)
        # and are not yet marked as completed OR were completed recently (e.g., last 6 hours) for score verification.
        commence_from_filter = now - timedelta(days=DAYS_FROM_FOR_SCORES)
        commence_to_filter = now + timedelta(minutes=30) # Games that just started or about to
        
        fixtures_to_check_q = models.Q(league=league) & \
                               (models.Q(completed=False, commence_time__gte=commence_from_filter, commence_time__lte=commence_to_filter) | \
                                models.Q(completed=True, updated_at__gte=now - timedelta(hours=6))) & \
                               (models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lte=now - timedelta(minutes=30))) # Check if not updated recently


        fixtures_to_check_scores_ids = list(FootballFixture.objects.filter(fixtures_to_check_q)
                                    .values_list('event_api_id', flat=True)
                                    .distinct()[:ODDS_FETCH_EVENT_BATCH_SIZE * 2])


        if not fixtures_to_check_scores_ids:
            logger.info(f"No fixtures found needing score updates for league {league.sport_key} at this time.")
            return f"No fixtures to check scores for {league.sport_key}."

        logger.info(f"Checking scores for {len(fixtures_to_check_scores_ids)} events in league {league.sport_key}.")
        scores_data = client.get_scores(sport_key=league.sport_key, event_ids=fixtures_to_check_scores_ids)

        if not scores_data: # API returned empty list
            logger.info(f"No scores data received from API for league {league.sport_key} for selected events.")
            FootballFixture.objects.filter(event_api_id__in=fixtures_to_check_scores_ids).update(last_score_update=timezone.now())
            return f"No scores data received for {league.sport_key} events."
        
        updated_count = 0
        settlement_tasks_triggered = 0
        processed_event_ids_scores = set()

        for score_item in scores_data:
            event_api_id = score_item.get('id')
            if not event_api_id: continue
            processed_event_ids_scores.add(event_api_id)
            
            try:
                with transaction.atomic():
                    fixture = FootballFixture.objects.get(event_api_id=event_api_id)
                    
                    is_completed_api = score_item.get('completed', fixture.completed) # Default to current if not in API resp
                    home_score_api_str = None
                    away_score_api_str = None
                    api_event_home_team = score_item.get('home_team') # Use for matching scores if names are consistent
                    api_event_away_team = score_item.get('away_team')

                    api_scores_list = score_item.get('scores')
                    if api_scores_list:
                        for team_score_data in api_scores_list:
                            # Match score to team based on name provided in the 'scores' object from API
                            if team_score_data.get('name') == api_event_home_team:
                                home_score_api_str = team_score_data.get('score')
                            elif team_score_data.get('name') == api_event_away_team:
                                away_score_api_str = team_score_data.get('score')
                    
                    needs_save = False
                    if home_score_api_str is not None and home_score_api_str.isdigit():
                        new_home_score = int(home_score_api_str)
                        if fixture.home_team_score != new_home_score:
                            fixture.home_team_score = new_home_score
                            needs_save = True
                    
                    if away_score_api_str is not None and away_score_api_str.isdigit():
                        new_away_score = int(away_score_api_str)
                        if fixture.away_team_score != new_away_score:
                            fixture.away_team_score = new_away_score
                            needs_save = True
                    
                    if fixture.completed != is_completed_api:
                        fixture.completed = is_completed_api
                        needs_save = True
                    
                    if needs_save or fixture.last_score_update is None or fixture.last_score_update < now - timedelta(minutes=29): # Avoid rapid updates if no change
                        fixture.last_score_update = now
                        fixture.save()
                        updated_count += 1
                        logger.info(f"Updated scores for fixture {event_api_id}: {fixture.home_team_name} {fixture.home_team_score} - {fixture.away_team_score} {fixture.away_team_name}. Completed: {fixture.completed}")

                        if fixture.completed and fixture.home_team_score is not None and fixture.away_team_score is not None:
                            # Check if outcomes are still pending before triggering settlement
                            if MarketOutcome.objects.filter(market__fixture_display=fixture, result_status='PENDING').exists():
                                logger.info(f"Triggering bet settlement for completed fixture {fixture.id} - {fixture.event_api_id}")
                                settle_bets_for_fixture_task.delay(fixture.id)
                                settlement_tasks_triggered +=1
                            else:
                                logger.info(f"Fixture {fixture.id} already settled or no pending outcomes.")
            except FootballFixture.DoesNotExist:
                logger.warning(f"Fixture {event_api_id} for score update not found in DB (sport_key: {league.sport_key}).")
            except Exception as e:
                logger.exception(f"Error updating scores for fixture {event_api_id}: {e}")
        
        # Mark events requested but not in score response as checked
        unchecked_event_ids = set(fixtures_to_check_scores_ids) - processed_event_ids_scores
        if unchecked_event_ids:
            FootballFixture.objects.filter(event_api_id__in=list(unchecked_event_ids)).update(last_score_update=now)

        logger.info(f"Task finished: fetch_scores_for_league_events_task for {league.sport_key}. Updated {updated_count} fixtures. Triggered {settlement_tasks_triggered} settlements.")
        return f"Scores update complete for {league.sport_key}. Updated {updated_count}."

    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_scores_for_league_events_task for {league.sport_key}: {e.status_code} - {e}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None:
            raise self.retry(exc=e)
        return f"Failed for {league.sport_key} due to API error: {e}"
    except Exception as e:
        logger.exception(f"Unexpected error in fetch_scores_for_league_events_task for {league.sport_key}.")
        raise self.retry(exc=e)


# --- Orchestrator Task (Updated with refined logic) ---

@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    logger.info("Orchestrator task: run_the_odds_api_full_update_task started.")

    # Step 1: Update Sports/Leagues (Consider if this needs to run every time or less frequently)
    # fetch_and_update_sports_leagues_task.apply_async() # .delay() is fine too

    active_leagues = League.objects.filter(active=True)
    if not active_leagues.exists():
        logger.info("No active leagues found to process.")
        return "No active leagues."

    for league in active_leagues:
        logger.info(f"Orchestrator: Processing league: {league.sport_key} ({league.name})")

        # Step 2a: Discover new events using /events endpoint (optional, /odds can also discover)
        # If your primary event discovery is via /odds, this can be run less frequently or skipped.
        # fetch_events_for_league_task.apply_async(args=[league.id])

        # Step 2b: Fetch Odds for relevant fixtures
        now = timezone.now()
        
        # Imminent events (e.g., starting in next 2 hours, update frequently)
        imminent_commence_max = now + timedelta(hours=2)
        imminent_staleness_threshold = now - timedelta(minutes=ODDS_IMMINENT_STALENESS_MINUTES)
        
        # Upcoming events (e.g., starting after 2 hours but within ODDS_LEAD_TIME_DAYS, update less frequently)
        upcoming_commence_max = now + timedelta(days=ODDS_LEAD_TIME_DAYS)
        upcoming_staleness_threshold = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)

        # Include events that just started, in case initial odds fetch was missed
        post_commencement_grace = now - timedelta(hours=ODDS_POST_COMMENCEMENT_GRACE_HOURS)


        # Query for fixtures needing odds update
        fixtures_needing_odds_q = models.Q(league=league, completed=False) & \
            (
                (models.Q(commence_time__gte=now) & models.Q(commence_time__lte=imminent_commence_max) & \
                    (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_staleness_threshold))) | \
                (models.Q(commence_time__gt=imminent_commence_max) & models.Q(commence_time__lte=upcoming_commence_max) & \
                    (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=upcoming_staleness_threshold))) | \
                (models.Q(commence_time__gte=post_commencement_grace) & models.Q(commence_time__lt=now) & \
                    (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_staleness_threshold))) # For recently started games
            )

        event_ids_for_odds = list(FootballFixture.objects.filter(fixtures_needing_odds_q)
                                  .values_list('event_api_id', flat=True)
                                  .distinct()[:ODDS_FETCH_EVENT_BATCH_SIZE * 5]) # Fetch a larger pool for batching
        
        if event_ids_for_odds:
            logger.info(f"Orchestrator: Found {len(event_ids_for_odds)} events in {league.sport_key} needing odds update.")
            for i in range(0, len(event_ids_for_odds), ODDS_FETCH_EVENT_BATCH_SIZE):
                batch_ids = event_ids_for_odds[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
                fetch_odds_for_events_task.apply_async(args=[league.sport_key, batch_ids])
        else:
            logger.info(f"Orchestrator: No events needing odds update for {league.sport_key} at this time based on criteria.")

        # Step 2c: Fetch Scores (this task has its own internal logic for selecting events)
        fetch_scores_for_league_events_task.apply_async(args=[league.id])

    logger.info("Orchestrator task: run_the_odds_api_full_update_task finished dispatching sub-tasks.")
    return "Full data update process initiated for active leagues."