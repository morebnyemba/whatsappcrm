# football_data_app/tasks.py
import logging
from django.conf import settings
from celery import shared_task, group
from django.db import transaction, IntegrityError, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException # Ensure this is correctly imported

logger = logging.getLogger(__name__)

# --- Settings or Defaults (ensure these are in your settings.py or defined here) ---
# These getattr calls will use values from your settings.py if defined,
# otherwise, they'll use the hardcoded defaults.
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 2)
ODDS_IMMINENT_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_IMMINENT_STALENESS_MINUTES', 15)
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
ODDS_POST_COMMENCEMENT_GRACE_HOURS = getattr(settings, 'THE_ODDS_API_POST_COMMENCEMENT_GRACE_HOURS', 1)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6) # How often to re-scan a league for basic events

# --- Helper Function for Parsing Outcome Details ---
def parse_outcome_details(outcome_name_api, market_key_api):
    name_part = outcome_name_api
    point_part = None
    if market_key_api in ['totals', 'h2h_spread'] or 'spreads' in market_key_api:
        try:
            parts = outcome_name_api.split()
            if len(parts) > 0:
                potential_point_str = parts[-1]
                if potential_point_str.replace('.', '', 1).lstrip('+-').isdigit():
                    point_part = float(potential_point_str)
                    if len(parts) > 1:
                        name_part = " ".join(parts[:-1])
                    else: # If only number was there
                        name_part = outcome_name_api # Or decide a default like "Total" or "Spread"
        except ValueError:
            logger.warning(f"Could not parse point from outcome: {outcome_name_api} for market {market_key_api}")
            name_part = outcome_name_api # Fallback
            point_part = None
    return name_part, point_part

# --- Bet Settlement Task ---
@shared_task(bind=True, max_retries=3, default_retry_delay=10 * 60)
def settle_bets_for_fixture_task(self, fixture_id):
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, completed=True, home_team_score__isnull=False, away_team_score__isnull=False)
        logger.info(f"Task started: settle_bets_for_fixture_task for Fixture ID: {fixture_id} ({fixture.home_team_name} vs {fixture.away_team_name})")

        home_score = fixture.home_team_score
        away_score = fixture.away_team_score
        outcomes_to_update = []

        for market in fixture.markets.all():
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'PENDING' # Default, will be changed if logic matches
                
                # --- H2H (Match Winner) ---
                if market.api_market_key == 'h2h':
                    # Assuming outcome_name for H2H is the team name or "Draw"
                    if outcome.outcome_name == fixture.home_team_name:
                        if home_score > away_score: new_status = 'WON'
                        else: new_status = 'LOST'
                    elif outcome.outcome_name == fixture.away_team_name:
                        if away_score > home_score: new_status = 'WON'
                        else: new_status = 'LOST'
                    elif outcome.outcome_name.lower() == 'draw':
                        if home_score == away_score: new_status = 'WON'
                        else: new_status = 'LOST'
                
                # --- Totals (Over/Under) ---
                elif market.api_market_key == 'totals':
                    total_score = home_score + away_score
                    if outcome.point_value is not None: # Expecting point_value to be set (e.g., 2.5)
                        if 'over' in outcome.outcome_name.lower(): # e.g., "Over"
                            if total_score > outcome.point_value: new_status = 'WON'
                            elif total_score == outcome.point_value: new_status = 'PUSH' # Or VOID depending on bookie rules
                            else: new_status = 'LOST'
                        elif 'under' in outcome.outcome_name.lower(): # e.g., "Under"
                            if total_score < outcome.point_value: new_status = 'WON'
                            elif total_score == outcome.point_value: new_status = 'PUSH'
                            else: new_status = 'LOST'
                
                # --- Spreads (Handicap) ---
                elif market.api_market_key in ['spreads', 'h2h_spread']: # Common keys for spreads
                    if outcome.point_value is not None:
                        # Assuming outcome_name is the team name for spreads
                        if outcome.outcome_name == fixture.home_team_name: # Bet on Home Team with spread
                            if (home_score + outcome.point_value) > away_score: new_status = 'WON'
                            elif (home_score + outcome.point_value) == away_score: new_status = 'PUSH' # For whole number spreads
                            else: new_status = 'LOST'
                        elif outcome.outcome_name == fixture.away_team_name: # Bet on Away Team with spread
                            if (away_score + outcome.point_value) > home_score: new_status = 'WON'
                            elif (away_score + outcome.point_value) == home_score: new_status = 'PUSH'
                            else: new_status = 'LOST'
                
                # TODO: Add logic for other market types as needed:
                # - Both Teams To Score (bts)
                # - Correct Score
                # - Etc.
                
                if new_status != 'PENDING' and new_status != outcome.result_status : # Only update if status changes
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


# --- Core Data Fetching Tasks ---
@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60)
def fetch_and_update_sports_leagues_task(self):
    client = TheOddsAPIClient()
    try:
        logger.info("Task started: fetch_and_update_sports_leagues_task")
        sports_data = client.get_sports(all_sports=True) # Fetches all available sports

        if not sports_data:
            logger.warning("No sports data received from API for leagues.")
            return "No sports data received."

        updated_count = 0
        created_count = 0
        for sport_item in sports_data:
            sport_key = sport_item.get('key')
            sport_title = sport_item.get('title')
            active_api = sport_item.get('active', True) # Default to True if not specified

            if not sport_key or not sport_title:
                logger.warning(f"Skipping sport item due to missing key or title: {sport_item}")
                continue

            with transaction.atomic():
                league, created = League.objects.update_or_create(
                    sport_key=sport_key,
                    defaults={
                        'name': sport_title, # Use the API title as the primary name
                        'sport_title': sport_title,
                        'active': active_api, # Can be overridden in admin
                    }
                )
                if created: 
                    created_count +=1
                    logger.info(f"Created League: {league.sport_key} - {league.name}")
                else: 
                    updated_count +=1
                    # logger.info(f"Updated League: {league.sport_key} - {league.name}") # Optional: log updates too
        
        logger.info(f"Task finished: fetch_and_update_sports_leagues_task. Created: {created_count}, Updated: {updated_count}.")
        return f"Sports/Leagues update complete. Created: {created_count}, Updated: {updated_count}."

    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_and_update_sports_leagues_task: {e.status_code} - {str(e)}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None: # Retry for server errors or rate limits
            raise self.retry(exc=e)
        return f"Failed due to API error: {str(e)}" # Non-retryable client error
    except Exception as e:
        logger.exception("Unexpected error in fetch_and_update_sports_leagues_task.")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=10 * 60)
def fetch_events_for_league_task(self, league_id):
    """Fetches basic event info (and discovers teams) for a league using the /events endpoint."""
    try:
        league = League.objects.get(id=league_id, active=True)
    except League.DoesNotExist:
        logger.warning(f"League with ID {league_id} not found or not active. Skipping event fetch.")
        return f"League {league_id} not found or inactive."

    client = TheOddsAPIClient()
    try:
        logger.info(f"Task started: fetch_events_for_league_task for League: {league.sport_key}")
        # The /events endpoint usually lists events without heavy quota use.
        # It's good for discovering event_ids and basic team names.
        events_data = client.get_events(sport_key=league.sport_key)

        if not events_data:
            logger.info(f"No events data received for league {league.sport_key} from /events endpoint.")
            league.last_fetched_events = timezone.now() # Mark as checked
            league.save()
            return f"No events data for {league.sport_key} via /events."

        created_count = 0
        updated_count = 0
        
        for event_item in events_data:
            event_api_id = event_item.get('id')
            commence_time_str = event_item.get('commence_time')
            home_team_name = event_item.get('home_team')
            away_team_name = event_item.get('away_team')
            sport_key_api = event_item.get('sport_key') # This is the sport_key of the event from API

            if not all([event_api_id, commence_time_str, home_team_name, away_team_name, sport_key_api]):
                logger.warning(f"Skipping event item from /events due to missing core data: {event_item} for league {league.sport_key}")
                continue
            
            try:
                commence_time = parser.isoparse(commence_time_str)
            except ValueError:
                logger.error(f"Could not parse commence_time '{commence_time_str}' from /events for event {event_api_id}. Skipping.")
                continue

            with transaction.atomic():
                # Get or create Team objects
                home_team_obj = Team.get_or_create_team(home_team_name)
                away_team_obj = Team.get_or_create_team(away_team_name)

                # Create or update FootballFixture
                fixture, created = FootballFixture.objects.update_or_create(
                    event_api_id=event_api_id, # Use API event ID as the unique key
                    defaults={
                        'league': league, # Link to the league this task is for
                        'sport_key': sport_key_api, # Store the event's specific sport_key
                        'commence_time': commence_time,
                        'home_team_name': home_team_name,
                        'away_team_name': away_team_name,
                        'home_team': home_team_obj, # Link to Team model
                        'away_team': away_team_obj, # Link to Team model
                        'completed': event_item.get('completed', False), # Update if API provides it
                    }
                )
                if created: 
                    created_count += 1
                    logger.info(f"Created Fixture (via /events): {fixture.event_api_id} for league {league.sport_key}")
                else: 
                    updated_count += 1
                    # logger.info(f"Updated Fixture (via /events): {fixture.event_api_id} for league {league.sport_key}")
        
        league.last_fetched_events = timezone.now() # Mark that this league's events were scanned
        league.save()
        
        logger.info(f"Task finished: fetch_events_for_league_task for {league.sport_key}. Processed from /events: {created_count+updated_count} (C:{created_count}, U:{updated_count}).")
        return f"Events update from /events complete for {league.sport_key}."
    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_events_for_league_task for {league.sport_key}: {e.status_code} - {str(e)}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None:
            raise self.retry(exc=e)
        # For other client errors (e.g., 404 if sport_key is bad), don't retry indefinitely from this specific task.
        return f"Failed for {league.sport_key} due to API error: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error in fetch_events_for_league_task for {league.sport_key}.")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=3 * 60) # Retries for API issues
def fetch_odds_for_events_task(self, sport_key, event_ids_list, regions=None, markets=None):
    current_regions = regions or getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "eu,uk")
    current_markets = markets or getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,spreads")
    client = TheOddsAPIClient() # API Key is handled by the client using settings
    odds_data_list = []

    if not event_ids_list: # Proactive fetch if no specific event_ids are provided
        logger.info(f"No specific event_ids provided for odds fetch (sport {sport_key}). Attempting proactive fetch for upcoming events.")
        now = timezone.now()
        commence_time_from_iso = now.isoformat()
        commence_time_to_iso = (now + timedelta(days=ODDS_LEAD_TIME_DAYS)).isoformat()
        try:
            odds_data_list = client.get_odds(
                sport_key=sport_key, regions=current_regions, markets=current_markets,
                commence_time_from=commence_time_from_iso, commence_time_to=commence_time_to_iso
            )
            logger.info(f"Proactive odds fetch for {sport_key} between {commence_time_from_iso} and {commence_time_to_iso} resulted in {len(odds_data_list)} events from API.")
        except TheOddsAPIException as e:
            logger.error(f"API Error during proactive odds fetch for {sport_key}: {e.status_code} - {str(e)}")
            if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None:
                raise self.retry(exc=e)
            return f"Proactive odds fetch failed for {sport_key} due to API error: {str(e)}"
        except Exception as e: # Catch any other unexpected error
            logger.exception(f"Unexpected error during proactive odds fetch for sport {sport_key}.")
            raise self.retry(exc=e) # Allow Celery to retry for unexpected issues
    else: # Specific event_ids were provided
        try:
            logger.info(f"Task started: fetch_odds_for_events_task for sport {sport_key}, {len(event_ids_list)} specific events. Regions: {current_regions}, Markets: {current_markets}")
            odds_data_list = client.get_odds(
                sport_key=sport_key, regions=current_regions, markets=current_markets, event_ids=event_ids_list
            )
        except TheOddsAPIException as e:
            logger.error(f"API Error in fetch_odds_for_events_task for sport {sport_key}, events {event_ids_list}: {e.status_code} - {str(e)}")
            if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None: # Retryable API errors
                raise self.retry(exc=e)
            # For non-retryable client errors (e.g. 400 bad request if event_ids are malformed, though client should catch this),
            # mark as checked to avoid loop.
            FootballFixture.objects.filter(event_api_id__in=event_ids_list, sport_key=sport_key).update(last_odds_update=timezone.now())
            return f"Failed for {sport_key} (specific events) due to non-retryable API error: {str(e)}"
        except Exception as e: # Catch any other unexpected error
            logger.exception(f"Unexpected error fetching odds for specific events in sport {sport_key}.")
            raise self.retry(exc=e) # Allow Celery to retry

    if not odds_data_list:
        logger.info(f"No odds data ultimately received from API for sport {sport_key} (events: {event_ids_list if event_ids_list else 'proactive fetch'}).")
        if event_ids_list: # Only update if specific IDs were requested and none found
            FootballFixture.objects.filter(event_api_id__in=event_ids_list, sport_key=sport_key).update(last_odds_update=timezone.now())
        return "No odds data received from API."

    processed_event_ids_in_response = set()
    for event_data_from_api in odds_data_list:
        event_api_id = event_data_from_api.get("id")
        home_team_name_api = event_data_from_api.get("home_team")
        away_team_name_api = event_data_from_api.get("away_team")
        commence_time_api_str = event_data_from_api.get("commence_time")
        event_sport_key_api = event_data_from_api.get("sport_key") # sport_key of the event itself from API response

        if not all([event_api_id, home_team_name_api, away_team_name_api, commence_time_api_str, event_sport_key_api]):
            logger.warning(f"Odds data for an event missing core fields (id, teams, commence_time, sport_key): {event_data_from_api}. Skipping.")
            continue
        
        processed_event_ids_in_response.add(event_api_id)
        try:
            commence_time_api = parser.isoparse(commence_time_api_str)
            
            # Get or create the League for the event's sport_key (could be different from requested sport_key if API returns related sports)
            league_obj, _ = League.objects.get_or_create(
                sport_key=event_sport_key_api, 
                defaults={'name': event_data_from_api.get('sport_title', event_sport_key_api.replace("_"," ").title())}
            )
            
            # Get or create Team objects
            home_team_obj = Team.get_or_create_team(home_team_name_api)
            away_team_obj = Team.get_or_create_team(away_team_name_api)

            # Create or update FootballFixture
            fixture, created = FootballFixture.objects.update_or_create(
                event_api_id=event_api_id,
                defaults={
                    'league': league_obj, 
                    'sport_key': event_sport_key_api, # Use the event's sport_key from API
                    'home_team_name': home_team_name_api,
                    'away_team_name': away_team_name_api,
                    'home_team': home_team_obj,
                    'away_team': away_team_obj,
                    'commence_time': commence_time_api,
                    # 'completed' status is usually from /scores endpoint, not typically in /odds
                }
            )
            if created: 
                logger.info(f"Fixture {event_api_id} ({home_team_name_api} vs {away_team_name_api}) created while processing odds.")
            
            with transaction.atomic():
                # Clear existing markets and outcomes for this fixture to get the latest state
                Market.objects.filter(fixture_display=fixture).delete() 

                for bookmaker_data in event_data_from_api.get("bookmakers", []):
                    bookmaker_key = bookmaker_data.get("key")
                    bookmaker_title = bookmaker_data.get("title")
                    if not bookmaker_key or not bookmaker_title: continue

                    bookie, _ = Bookmaker.objects.update_or_create(
                        api_bookmaker_key=bookmaker_key, defaults={'name': bookmaker_title}
                    )

                    for market_data in bookmaker_data.get("markets", []):
                        market_key_api = market_data.get("key") # e.g., "h2h", "totals"
                        market_last_update_str = market_data.get("last_update")
                        if not market_key_api or not market_last_update_str: continue
                        
                        try:
                            market_api_last_update_dt = parser.isoparse(market_last_update_str)
                        except ValueError:
                            logger.error(f"Could not parse market_last_update '{market_last_update_str}' for event {event_api_id}, market {market_key_api}. Skipping market.")
                            continue

                        category_name = market_key_api.replace("_", " ").title() # Basic mapping
                        market_category, _ = MarketCategory.objects.get_or_create(name=category_name)

                        market_instance = Market.objects.create( # Using create since old ones deleted
                            fixture_display=fixture, 
                            bookmaker=bookie, 
                            api_market_key=market_key_api,
                            category=market_category, 
                            last_updated_odds_api=market_api_last_update_dt
                        )
                        
                        for outcome_data in market_data.get("outcomes", []):
                            outcome_name_api = outcome_data.get("name")
                            outcome_price_str = outcome_data.get("price") # API sends price as string or number
                            if outcome_name_api is None or outcome_price_str is None: continue
                            
                            try:
                                odds_decimal = float(outcome_price_str)
                            except ValueError:
                                logger.error(f"Invalid price format '{outcome_price_str}' for outcome '{outcome_name_api}', event {event_api_id}. Skipping outcome.")
                                continue
                                
                            parsed_name, parsed_point = parse_outcome_details(outcome_name_api, market_key_api)

                            MarketOutcome.objects.create(
                                market=market_instance, 
                                outcome_name=parsed_name,
                                odds=odds_decimal, 
                                point_value=parsed_point
                            )
                fixture.last_odds_update = timezone.now()
                fixture.save()
                logger.info(f"Successfully processed odds for event {event_api_id} ({fixture.home_team_name} vs {fixture.away_team_name})")

        except IntegrityError as e: 
            logger.error(f"Database integrity error while processing odds for event {event_api_id}: {e}")
        except Exception as e: 
            logger.exception(f"Unexpected error processing odds data for event {event_api_id}: {e}")

    # If specific event_ids were requested, mark any not found in response as checked
    if event_ids_list: 
        unprocessed_event_ids = set(event_ids_list) - processed_event_ids_in_response
        if unprocessed_event_ids:
            FootballFixture.objects.filter(event_api_id__in=list(unprocessed_event_ids), sport_key=sport_key).update(last_odds_update=timezone.now())
            logger.info(f"Marked {len(unprocessed_event_ids)} requested events as checked (no odds data returned in response): {','.join(list(unprocessed_event_ids))}")

    logger.info(f"Task finished: fetch_odds_for_events_task for sport {sport_key}. Processed {len(processed_event_ids_in_response)} events from API response.")
    return f"Odds update complete for {len(processed_event_ids_in_response)} events in sport {sport_key}."


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
        days_from_for_scores_val = getattr(settings, 'THE_ODDS_API_DAYS_FROM_SCORES', 3)
        batch_size_val = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10) # How many events to query scores for at once

        # Define time window for selecting fixtures
        commence_from_filter = now - timedelta(days=days_from_for_scores_val) # Games that started up to X days ago
        commence_to_filter = now + timedelta(minutes=30) # Games that just started or are about to end

        # Select fixtures needing score updates
        fixtures_to_check_q = models.Q(league=league) & \
                               (models.Q(completed=False, commence_time__gte=commence_from_filter, commence_time__lte=commence_to_filter) | \
                                models.Q(completed=True, updated_at__gte=now - timedelta(hours=6))) & \
                               (models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lte=now - timedelta(minutes=30))) # Check if not updated recently

        fixtures_to_check_scores_ids = list(FootballFixture.objects.filter(fixtures_to_check_q)
                                    .values_list('event_api_id', flat=True)
                                    .distinct()[:batch_size_val * 2]) # Limit to a reasonable number per run

        if not fixtures_to_check_scores_ids:
            logger.info(f"No fixtures found needing score updates for league {league.sport_key} at this time.")
            return f"No fixtures to check scores for {league.sport_key}."

        logger.info(f"Checking scores for {len(fixtures_to_check_scores_ids)} events in league {league.sport_key}.")
        scores_data = client.get_scores(sport_key=league.sport_key, event_ids=fixtures_to_check_scores_ids)

        if not scores_data: # API returned empty list for the given event_ids
            logger.info(f"No scores data received from API for league {league.sport_key} for selected events: {fixtures_to_check_scores_ids}.")
            # Mark these as checked to avoid immediate re-fetch
            FootballFixture.objects.filter(event_api_id__in=fixtures_to_check_scores_ids).update(last_score_update=timezone.now())
            return f"No scores data received for {league.sport_key} events."
        
        updated_count = 0
        settlement_tasks_triggered = 0
        processed_event_ids_scores = set()

        for score_item in scores_data:
            event_api_id = score_item.get('id')
            if not event_api_id: 
                logger.warning(f"Score item missing 'id': {score_item} for league {league.sport_key}. Skipping.")
                continue
            processed_event_ids_scores.add(event_api_id)
            
            try:
                with transaction.atomic():
                    # It's possible the fixture was created by odds fetch for a different sport_key if API returns related events
                    # So, query by event_api_id only initially.
                    fixture = FootballFixture.objects.get(event_api_id=event_api_id) 
                    
                    is_completed_api = score_item.get('completed', fixture.completed) # Default to current if not in API resp
                    home_score_api_str, away_score_api_str = None, None
                    
                    # Use team names from the score_item itself for matching, as they are directly associated with the scores
                    api_event_home_team = score_item.get('home_team') 
                    api_event_away_team = score_item.get('away_team')

                    api_scores_list = score_item.get('scores')
                    if api_scores_list:
                        for team_score_data in api_scores_list:
                            team_name_in_score = team_score_data.get('name')
                            team_score_value_str = team_score_data.get('score')
                            if team_name_in_score == api_event_home_team: 
                                home_score_api_str = team_score_value_str
                            elif team_name_in_score == api_event_away_team:
                                away_score_api_str = team_score_value_str
                    
                    needs_save = False
                    # Update home score if changed
                    if home_score_api_str is not None and home_score_api_str.isdigit():
                        new_home_score = int(home_score_api_str)
                        if fixture.home_team_score != new_home_score:
                            fixture.home_team_score = new_home_score
                            needs_save = True
                    elif home_score_api_str is None and fixture.home_team_score is not None: # API cleared score
                        fixture.home_team_score = None
                        needs_save = True

                    # Update away score if changed
                    if away_score_api_str is not None and away_score_api_str.isdigit():
                        new_away_score = int(away_score_api_str)
                        if fixture.away_team_score != new_away_score:
                            fixture.away_team_score = new_away_score
                            needs_save = True
                    elif away_score_api_str is None and fixture.away_team_score is not None: # API cleared score
                        fixture.away_team_score = None
                        needs_save = True
                    
                    # Update completed status if changed
                    if fixture.completed != is_completed_api:
                        fixture.completed = is_completed_api
                        needs_save = True
                    
                    # Update timestamp only if there was a change or if it's time for a refresh
                    if needs_save or fixture.last_score_update is None or fixture.last_score_update < now - timedelta(minutes=29):
                        fixture.last_score_update = now # Update regardless of needs_save if stale
                        if needs_save: # Only save if actual data changed
                           fixture.save()
                           updated_count += 1
                           logger.info(f"Updated scores for fixture {event_api_id}: {fixture.home_team_name} {fixture.home_team_score} - {fixture.away_team_score} {fixture.away_team_name}. Completed: {fixture.completed}")
                        else: # Only timestamp updated
                           FootballFixture.objects.filter(pk=fixture.pk).update(last_score_update=now)


                        # Trigger settlement if completed and scores are present
                        if fixture.completed and fixture.home_team_score is not None and fixture.away_team_score is not None:
                            if MarketOutcome.objects.filter(market__fixture_display=fixture, result_status='PENDING').exists():
                                logger.info(f"Triggering bet settlement for completed fixture {fixture.id} - {fixture.event_api_id}")
                                settle_bets_for_fixture_task.delay(fixture.id)
                                settlement_tasks_triggered +=1
                            # else:
                                # logger.info(f"Fixture {fixture.id} already settled or no pending outcomes.")
            except FootballFixture.DoesNotExist: 
                logger.warning(f"Fixture {event_api_id} for score update not found in DB (sport_key: {league.sport_key}). It might be for a different league than expected or not yet created by odds fetch.")
            except Exception as e: 
                logger.exception(f"Error updating scores for fixture {event_api_id}: {e}")
        
        # Mark events requested but not in score response as checked
        unchecked_event_ids = set(fixtures_to_check_scores_ids) - processed_event_ids_scores
        if unchecked_event_ids:
            FootballFixture.objects.filter(event_api_id__in=list(unchecked_event_ids)).update(last_score_update=now)
            logger.info(f"Marked {len(unchecked_event_ids)} events as checked for scores (no data in API response): {','.join(list(unchecked_event_ids))}")

        logger.info(f"Task finished: fetch_scores_for_league_events_task for {league.sport_key}. Updated {updated_count} fixtures. Triggered {settlement_tasks_triggered} settlements.")
        return f"Scores update complete for {league.sport_key}. Updated {updated_count}."
    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_scores_for_league_events_task for {league.sport_key}: {e.status_code} - {str(e)}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None: raise self.retry(exc=e)
        return f"Failed for {league.sport_key} due to API error: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error in fetch_scores_for_league_events_task for {league.sport_key}.")
        raise self.retry(exc=e)


# --- Orchestrator Task ---
@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    logger.info("Orchestrator task: run_the_odds_api_full_update_task started.")

    # Step 1: Update Sports/Leagues from API
    # This ensures the list of available leagues (sport_keys) is up-to-date.
    # Run this asynchronously. Consider if this needs to run every time the orchestrator runs,
    # or perhaps on a less frequent, separate schedule (e.g., daily).
    # For now, triggering it to ensure leagues are fresh before processing.
    fetch_and_update_sports_leagues_task.apply_async()

    active_leagues = League.objects.filter(active=True)
    if not active_leagues.exists():
        logger.info("Orchestrator: No active leagues found to process. Ensure leagues are fetched and marked active in Admin.")
        return "No active leagues."

    now = timezone.now()
    event_discovery_staleness_threshold = now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)
    
    # Get dynamic settings for odds fetching from Django settings
    odds_lead_time_days_val = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 2)
    odds_imminent_staleness_minutes_val = getattr(settings, 'THE_ODDS_API_IMMINENT_STALENESS_MINUTES', 15)
    odds_upcoming_staleness_minutes_val = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
    odds_post_commencement_grace_hours_val = getattr(settings, 'THE_ODDS_API_POST_COMMENCEMENT_GRACE_HOURS', 1)
    batch_size_val = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)

    for league in active_leagues:
        logger.info(f"Orchestrator: Processing league: {league.sport_key} ({league.name})")

        # Step 2a: Discover events (and implicitly teams) if not scanned recently for this league
        # This uses the /events endpoint, good for finding event IDs and basic team info.
        if league.last_fetched_events is None or league.last_fetched_events < event_discovery_staleness_threshold:
            logger.info(f"Orchestrator: League {league.sport_key} needs event discovery (last checked: {league.last_fetched_events}). Dispatching fetch_events_for_league_task.")
            fetch_events_for_league_task.apply_async(args=[league.id])
        else:
            logger.info(f"Orchestrator: League {league.sport_key} event discovery is recent (last checked: {league.last_fetched_events}). Skipping explicit event fetch via /events.")

        # Step 2b: Fetch Odds for relevant fixtures for this league
        # This logic tries to find existing fixtures that need an odds update OR
        # triggers a proactive search for new upcoming fixtures if none are found matching criteria.
        
        # Define time thresholds for odds fetching
        imminent_commence_max = now + timedelta(hours=2) # Could be a setting
        imminent_staleness_threshold = now - timedelta(minutes=odds_imminent_staleness_minutes_val)
        
        upcoming_commence_max = now + timedelta(days=odds_lead_time_days_val)
        upcoming_staleness_threshold = now - timedelta(minutes=odds_upcoming_staleness_minutes_val)
        
        post_commencement_grace_min_time = now - timedelta(hours=odds_post_commencement_grace_hours_val)

        # Query for existing fixtures in this league that need an odds update
        fixtures_needing_odds_q = models.Q(league=league, completed=False) & \
            (
                # Imminent games needing update
                (models.Q(commence_time__gte=now) & models.Q(commence_time__lte=imminent_commence_max) & \
                    (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_staleness_threshold))) |
                # Upcoming (but not imminent) games needing update
                (models.Q(commence_time__gt=imminent_commence_max) & models.Q(commence_time__lte=upcoming_commence_max) & \
                    (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=upcoming_staleness_threshold))) |
                # Games that recently started and might have missed initial odds fetch
                (models.Q(commence_time__gte=post_commencement_grace_min_time) & models.Q(commence_time__lt=now) & \
                    (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_staleness_threshold)))
            )
        
        event_ids_for_odds = list(FootballFixture.objects.filter(fixtures_needing_odds_q)
                                  .values_list('event_api_id', flat=True)
                                  .distinct()[:batch_size_val * 5]) # Fetch a pool of IDs

        if event_ids_for_odds:
            logger.info(f"Orchestrator: Found {len(event_ids_for_odds)} existing events in {league.sport_key} needing odds update.")
            for i in range(0, len(event_ids_for_odds), batch_size_val): # Process in batches
                batch_ids = event_ids_for_odds[i:i + batch_size_val]
                fetch_odds_for_events_task.apply_async(args=[league.sport_key, batch_ids])
        else:
            # If no existing fixtures match criteria, do a proactive fetch for NEW upcoming events for this league
            logger.info(f"Orchestrator: No existing events match odds update criteria for {league.sport_key}. Attempting proactive odds fetch for new upcoming events.")
            # Pass empty list to fetch_odds_for_events_task to trigger its proactive fetching logic
            fetch_odds_for_events_task.apply_async(args=[league.sport_key, []]) 

        # Step 2c: Fetch Scores for the league (task has its own logic to select relevant fixtures)
        fetch_scores_for_league_events_task.apply_async(args=[league.id])

    logger.info("Orchestrator task: run_the_odds_api_full_update_task finished dispatching sub-tasks.")
    return "Full data update process initiated for active leagues."

