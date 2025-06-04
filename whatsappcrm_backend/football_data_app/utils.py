import requests
import time # For adding delays to respect API rate limits
import logging # For better logging
from datetime import datetime, timezone
from django.conf import settings
from django.db import transaction
from dateutil import parser as dateutil_parser # For flexible date parsing, pip install python-dateutil

# Import your models from the football_data_app
from .models import (
    League, Team, FootballFixture, Bookmaker,
    MarketCategory, Market, MarketOutcome
)

# --- Setup Logging ---
logger = logging.getLogger(__name__) # Get a logger instance for this module

# --- Configuration ---
API_BASE_URL = "https://v3.football.api-sports.io" # Confirm this base URL from api-football docs
API_KEY = getattr(settings, 'API_FOOTBALL_KEY', None)
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io", # Confirm this from api-football docs
    'x-rapidapi-key': API_KEY
}
# Seconds to wait between batches of API calls to respect rate limits
API_CALL_DELAY_SECONDS = getattr(settings, 'API_FOOTBALL_CALL_DELAY_SECONDS', 2) # Default to 2 seconds


# --- Helper Functions ---

def _make_api_request(endpoint, params=None, page=None):
    """
    Helper function to make requests to the api-football API.
    Includes basic pagination parameter if API supports it.
    """
    if not API_KEY:
        logger.error("API_FOOTBALL_KEY not configured in settings.")
        return None

    url = f"{API_BASE_URL}/{endpoint}"
    current_params = params.copy() if params else {}

    # Basic pagination: Most APIs use 'page' or 'offset'/'limit'.
    # This is a common way; refer to api-football docs for their specific pagination params.
    if page is not None:
        current_params['page'] = page # Or whatever their page parameter is

    try:
        logger.debug(f"Making API request to URL: {url} with params: {current_params}")
        response = requests.get(url, headers=HEADERS, params=current_params, timeout=30) # 30 second timeout
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)

        # Check for API-specific errors if they have a common error structure in the JSON body
        response_data = response.json() # Parse JSON once
        # Example: response_data.get('errors')
        if isinstance(response_data, dict) and response_data.get('errors') and response_data['errors']: # Check if dict and errors exist
             # API errors can be a list or a string, handle appropriately
            api_errors = response_data['errors']
            if isinstance(api_errors, list) and len(api_errors) > 0:
                 # If errors is a list of strings or dicts
                logger.error(f"API returned errors: {api_errors} for URL: {url} with params: {current_params}")
            elif isinstance(api_errors, str) and len(api_errors) > 0 : # If errors is a string
                logger.error(f"API returned error string: {api_errors} for URL: {url} with params: {current_params}")
            # else: errors might be an empty list or dict, which is not an error state by itself
            # Depending on API, you might still want to return None if 'errors' key exists and is non-empty
            # For now, we'll only log and return None if errors are substantive
            if api_errors: # If errors is not empty
                 return None


        return response_data
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err} - URL: {url} - Status: {http_err.response.status_code} - Response: {http_err.response.text}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"Connection error occurred: {conn_err} - URL: {url}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"Timeout error occurred: {timeout_err} - URL: {url}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"An error occurred during API request: {req_err} - URL: {url}")
    except ValueError as json_err: # Includes JSONDecodeError if response.json() fails
        logger.error(f"JSON decode error: {json_err} - URL: {url} - Response Text: {response.text if 'response' in locals() else 'N/A'}")
    return None

def parse_datetime_from_api(datetime_str, field_name="datetime"):
    """
    Parses datetime strings from API.
    """
    if datetime_str is None:
        return None
    try:
        if isinstance(datetime_str, (int, float)): # Unix timestamp
            # Ensure the timestamp is within a reasonable range if necessary
            return datetime.fromtimestamp(datetime_str, tz=timezone.utc if settings.USE_TZ else None)
        # ISO 8601 string
        dt_obj = dateutil_parser.isoparse(datetime_str)
        if settings.USE_TZ and dt_obj.tzinfo is None: # Ensure timezone awareness if USE_TZ is True
             dt_obj = dt_obj.replace(tzinfo=timezone.utc) # Assume UTC if not specified by API and Django uses TZ
        return dt_obj
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse {field_name}: '{datetime_str}'. Error: {e}")
        return None

def _get_api_paging_info(response_data):
    """
    Extracts paging information from API response.
    api-football example: 'paging': {'current': 1, 'total': 10}
    Returns: (current_page, total_pages) or (None, None) if not found.
    """
    if not isinstance(response_data, dict): # Ensure response_data is a dict
        logger.debug("Paging info check: response_data is not a dictionary.")
        return None, None

    paging = response_data.get('paging')
    if paging and isinstance(paging, dict):
        current_page = paging.get('current')
        total_pages = paging.get('total')
        if current_page is not None and total_pages is not None:
            try:
                return int(current_page), int(total_pages)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse paging info: current='{current_page}', total='{total_pages}'")
                return None, None
    logger.debug("Paging information not found or incomplete in API response's 'paging' dictionary.")
    return None, None


# --- Data Fetching and Processing Functions ---

@transaction.atomic
def fetch_and_update_leagues(league_ids=None, country_code=None, season=None):
    logger.info(f"Starting league fetch. IDs: {league_ids}, Country: {country_code}, Season: {season}")
    params = {}
    if league_ids:
        if isinstance(league_ids, list) and len(league_ids) == 1: params['id'] = league_ids[0]
        elif isinstance(league_ids, int): params['id'] = league_ids
        elif isinstance(league_ids, list) and len(league_ids) > 1:
            logger.info(f"Fetching multiple specific league IDs: {len(league_ids)}. Iterating if API doesn't support bulk IDs for 'leagues' endpoint.")
            # Assuming 'leagues' endpoint with 'id' param takes one ID. If it supports comma-separated, adjust here.
            for lid in league_ids:
                fetch_and_update_leagues(league_ids=[lid], country_code=country_code, season=season) # Recursive call
                time.sleep(API_CALL_DELAY_SECONDS) # Delay between individual calls
            return # Return after iterating
    if country_code: params['country'] = country_code
    if season: params['season'] = season

    current_page = 1
    total_pages = 1
    all_league_data_wrappers = []

    while current_page <= total_pages:
        logger.info(f"Fetching leagues page {current_page} of {total_pages} with params {params}...")
        data = _make_api_request("leagues", params=params, page=current_page)
        if not data:
            logger.error(f"Failed to fetch leagues page {current_page} for params: {params}. Aborting for these params.")
            return

        api_response_leagues = data.get("response", [])
        if not isinstance(api_response_leagues, list): # Expecting a list
            logger.error(f"API 'response' for leagues is not a list as expected. Received: {type(api_response_leagues)}. Params: {params}")
            return
        if not api_response_leagues and current_page == 1 and total_pages == 1: # No results on first assumed page
            logger.info(f"No league data found in 'response' on page {current_page} for params: {params}")
            break

        all_league_data_wrappers.extend(api_response_leagues)

        if current_page == 1: # Check paging info only on first successful page fetch
            _, total_pages_from_api = _get_api_paging_info(data)
            if total_pages_from_api is not None:
                total_pages = total_pages_from_api
                logger.info(f"Total pages for leagues: {total_pages}")
            else: # No paging info, assume single page
                logger.info("No paging info found for leagues; assuming single page.")
                break

        if current_page >= total_pages:
            break
        current_page += 1
        time.sleep(API_CALL_DELAY_SECONDS)

    leagues_created_count = 0
    leagues_updated_count = 0
    for league_data_wrapper in all_league_data_wrappers:
        try:
            if not isinstance(league_data_wrapper, dict):
                logger.warning(f"Skipping league entry, not a dictionary: {league_data_wrapper}")
                continue
            league_info = league_data_wrapper.get("league")
            country_info = league_data_wrapper.get("country")
            if not isinstance(league_info, dict) or not league_info.get("id"):
                logger.warning(f"Skipping league entry due to missing ID or invalid 'league' data structure: {league_data_wrapper}")
                continue

            defaults = {
                'name': league_info.get("name", "N/A"),
                'logo_url': league_info.get("logo"),
            }
            if isinstance(country_info, dict):
                defaults['country'] = country_info.get("name")

            _, created = League.objects.update_or_create(
                api_league_id=league_info["id"],
                defaults=defaults
            )
            if created: leagues_created_count += 1
            else: leagues_updated_count +=1
        except Exception as e:
            logger.error(f"Error processing league data: {league_data_wrapper}. Error: {e}", exc_info=True)
    logger.info(f"Leagues fetch complete: {leagues_created_count} created, {leagues_updated_count} updated from {len(all_league_data_wrappers)} API entries.")


@transaction.atomic
def fetch_and_update_teams_for_league_season(league_api_id, season_year):
    logger.info(f"Starting team fetch for league API ID {league_api_id}, season {season_year}")
    try:
        League.objects.get(api_league_id=league_api_id)
    except League.DoesNotExist:
        logger.error(f"League with api_league_id {league_api_id} not found. Cannot fetch teams.")
        return

    params = {'league': league_api_id, 'season': season_year}
    current_page = 1
    total_pages = 1
    all_team_data_wrappers = []

    while current_page <= total_pages:
        logger.info(f"Fetching teams page {current_page} of {total_pages} for league {league_api_id}, season {season_year}...")
        data = _make_api_request("teams", params=params, page=current_page)
        if not data:
            logger.error(f"Failed to fetch teams page {current_page} for league {league_api_id}, season {season_year}.")
            return

        api_response_teams = data.get("response", [])
        if not isinstance(api_response_teams, list):
            logger.error(f"API 'response' for teams is not a list. Received: {type(api_response_teams)}. Params: {params}")
            return
        if not api_response_teams and current_page == 1 and total_pages == 1:
            logger.info(f"No team data found in 'response' on page {current_page} for league {league_api_id}, season {season_year}.")
            break

        all_team_data_wrappers.extend(api_response_teams)

        if current_page == 1:
            _, total_pages_from_api = _get_api_paging_info(data)
            if total_pages_from_api is not None:
                total_pages = total_pages_from_api
                logger.info(f"Total pages for teams: {total_pages}")
            else:
                logger.info("No paging info found for teams; assuming single page.")
                break

        if current_page >= total_pages:
            break
        current_page += 1
        time.sleep(API_CALL_DELAY_SECONDS)

    teams_created_count = 0
    teams_updated_count = 0
    for team_data_wrapper in all_team_data_wrappers:
        try:
            if not isinstance(team_data_wrapper, dict):
                logger.warning(f"Skipping team entry, not a dictionary: {team_data_wrapper}")
                continue
            team_info = team_data_wrapper.get("team")
            # venue_info = team_data_wrapper.get("venue") # Uncomment if you store venue details with Team
            if not isinstance(team_info, dict) or not team_info.get("id"):
                logger.warning(f"Skipping team entry due to missing ID or invalid 'team' data structure: {team_data_wrapper}")
                continue

            defaults = {
                'name': team_info.get("name", "N/A"),
                'code': team_info.get("code"),
                'logo_url': team_info.get("logo"),
                'country': team_info.get("country"),
                # Add venue data if your Team model has fields for it
                # 'venue_name': venue_info.get("name") if isinstance(venue_info, dict) else None,
            }
            _, created = Team.objects.update_or_create(
                api_team_id=team_info["id"],
                defaults=defaults
            )
            if created: teams_created_count += 1
            else: teams_updated_count +=1
        except Exception as e:
            logger.error(f"Error processing team data: {team_data_wrapper}. Error: {e}", exc_info=True)
    logger.info(f"Teams for league {league_api_id}, season {season_year} fetch complete: {teams_created_count} created, {teams_updated_count} updated.")


@transaction.atomic
def fetch_and_update_fixtures(league_api_id=None, season_year=None, date_from_str=None, date_to_str=None, fixture_api_ids=None):
    logger.info(f"Starting fixture fetch. League: {league_api_id}, Season: {season_year}, Dates: {date_from_str}-{date_to_str}, IDs: {fixture_api_ids}")
    params = {}
    if fixture_api_ids:
        # API for fixtures might use 'id' for a single fixture, or 'ids' for multiple (e.g., 'id1-id2-id3')
        # Consult api-football documentation for how to query multiple specific fixture IDs.
        if isinstance(fixture_api_ids, list):
            if len(fixture_api_ids) == 1:
                params['id'] = fixture_api_ids[0]
            else: # Example for 'ids' param, replace 'ids_param_name' and format if different
                # params['ids_param_name'] = '-'.join(map(str, fixture_api_ids))
                # If iteration is the only way for multiple specific fixtures:
                logger.info(f"Fetching multiple specific fixture IDs: {len(fixture_api_ids)} by iterating.")
                for fid in fixture_api_ids:
                    fetch_and_update_fixtures(fixture_api_ids=[fid]) # Recursive call for single ID
                    time.sleep(API_CALL_DELAY_SECONDS)
                return
        elif isinstance(fixture_api_ids, (int, str)): # Single ID
            params['id'] = fixture_api_ids
    else: # Params for league/season/date range
        if league_api_id: params['league'] = league_api_id
        if season_year: params['season'] = season_year
        if date_from_str: params['from'] = date_from_str # API format usually YYYY-MM-DD
        if date_to_str: params['to'] = date_to_str
        if date_from_str and not date_to_str and 'from' not in params: # API might use 'date' for a single day
            params['date'] = date_from_str

    if not params:
        logger.warning("Fixture fetch called without any identifying parameters. Aborting.")
        return

    current_page = 1
    total_pages = 1
    all_fixture_data_wrappers = []

    while current_page <= total_pages:
        logger.info(f"Fetching fixtures page {current_page} of {total_pages} with params {params}...")
        data = _make_api_request("fixtures", params=params, page=current_page)
        if not data:
            logger.error(f"Failed to fetch fixtures page {current_page} with params {params}. Aborting for these params.")
            return

        api_response_fixtures = data.get("response", [])
        if not isinstance(api_response_fixtures, list):
            logger.error(f"API 'response' for fixtures is not a list. Received: {type(api_response_fixtures)}. Params: {params}")
            return
        if not api_response_fixtures and current_page == 1 and total_pages == 1:
            logger.info(f"No fixture data found in 'response' on page {current_page} for params: {params}")
            break

        all_fixture_data_wrappers.extend(api_response_fixtures)

        if current_page == 1:
            _, total_pages_from_api = _get_api_paging_info(data)
            if total_pages_from_api is not None:
                total_pages = total_pages_from_api
                logger.info(f"Total pages for fixtures: {total_pages}")
            else:
                logger.info("No paging info found for fixtures; assuming single page.")
                break

        if current_page >= total_pages:
            break
        current_page += 1
        time.sleep(API_CALL_DELAY_SECONDS)

    fixtures_created = 0
    fixtures_updated = 0
    for fixture_data in all_fixture_data_wrappers:
        try:
            if not isinstance(fixture_data, dict):
                logger.warning(f"Skipping fixture entry, not a dictionary: {fixture_data}")
                continue

            fix_info = fixture_data.get("fixture", {})
            league_info = fixture_data.get("league", {})
            home_team_info = fixture_data.get("teams", {}).get("home", {})
            away_team_info = fixture_data.get("teams", {}).get("away", {})
            goals_info = fixture_data.get("goals", {}) # Contains home/away final scores
            score_info = fixture_data.get("score", {}) # Contains halftime, fulltime, extratime, penalty scores

            # Validate critical IDs
            fixture_api_id = fix_info.get("id")
            league_api_id_from_fixture = league_info.get("id")
            home_team_api_id = home_team_info.get("id")
            away_team_api_id = away_team_info.get("id")

            if not all([fixture_api_id, league_api_id_from_fixture, home_team_api_id, away_team_api_id]):
                logger.warning(f"Skipping fixture due to missing critical IDs: Fixture({fixture_api_id}), League({league_api_id_from_fixture}), Home({home_team_api_id}), Away({away_team_api_id}). Data: {fixture_data}")
                continue
            
            match_api_id_str = str(fixture_api_id)

            # Get related objects, log warning if not found but don't necessarily stop all processing
            league_obj = League.objects.filter(api_league_id=league_api_id_from_fixture).first()
            home_team_obj = Team.objects.filter(api_team_id=home_team_api_id).first()
            away_team_obj = Team.objects.filter(api_team_id=away_team_api_id).first()

            if not league_obj: logger.warning(f"League {league_api_id_from_fixture} not found for fixture {match_api_id_str}. Fixture will have no league link.")
            if not home_team_obj: logger.warning(f"Home team {home_team_api_id} not found for fixture {match_api_id_str}. Fixture will have no home team link.")
            if not away_team_obj: logger.warning(f"Away team {away_team_api_id} not found for fixture {match_api_id_str}. Fixture will have no away team link.")
            
            # Prepare defaults for FootballFixture model
            fixture_defaults = {
                'league': league_obj, # Can be None if not found and model allows
                'home_team': home_team_obj, # Can be None
                'away_team': away_team_obj, # Can be None
                'match_date': parse_datetime_from_api(fix_info.get("date"), "fixture.date"),
                'status_short': fix_info.get("status", {}).get("short", "N/A"),
                'status_long': fix_info.get("status", {}).get("long", "Not Available"),
                'venue_name': fix_info.get("venue", {}).get("name"),
                'referee': fix_info.get("referee"),
                'round': league_info.get("round"), # Typically from league context within fixture data
                
                # Scores from 'goals' usually represent the main scoreline after full events
                'home_team_score': goals_info.get("home"),
                'away_team_score': goals_info.get("away"),
                
                # Detailed scores from 'score' object
                'halftime_home_score': score_info.get("halftime", {}).get("home"),
                'halftime_away_score': score_info.get("halftime", {}).get("away"),
                'extratime_home_score': score_info.get("extratime", {}).get("home"),
                'extratime_away_score': score_info.get("extratime", {}).get("away"),
                'penalty_home_score': score_info.get("penalty", {}).get("home"),
                'penalty_away_score': score_info.get("penalty", {}).get("away"),
                
                'api_fixture_timestamp': parse_datetime_from_api(fix_info.get("timestamp"), "fixture.timestamp"), # API's own update timestamp for the fixture
                # Define which statuses mean the result is confirmed for settlement
                'is_result_confirmed': fix_info.get("status", {}).get("short") in ["FT", "AET", "PEN", "AWDD", "ABD", "WO"] # Add all applicable finished/awarded/walkover statuses
            }
            
            _, created = FootballFixture.objects.update_or_create(
                match_api_id=match_api_id_str,
                defaults=fixture_defaults
            )
            if created: fixtures_created += 1
            else: fixtures_updated += 1

        except Exception as e:
            logger.error(f"Error processing fixture data: {fixture_data}. Error: {e}", exc_info=True)
    logger.info(f"Fixtures fetch complete: {fixtures_created} created, {fixtures_updated} updated from {len(all_fixture_data_wrappers)} API entries.")


@transaction.atomic
def fetch_and_update_odds_for_fixture(fixture_api_id, bookmaker_api_id_filter=None):
    logger.info(f"Starting odds fetch for fixture API ID {fixture_api_id}. Bookmaker filter: {bookmaker_api_id_filter}")
    try:
        fixture_obj = FootballFixture.objects.get(match_api_id=str(fixture_api_id))
    except FootballFixture.DoesNotExist:
        logger.error(f"Fixture with match_api_id {fixture_api_id} not found. Cannot fetch odds.")
        return

    params = {'fixture': fixture_api_id}
    if bookmaker_api_id_filter:
        params['bookmaker'] = bookmaker_api_id_filter # API param for specific bookmaker ID

    # The "odds" endpoint in api-football (when queried with a fixture ID)
    # usually returns a list where each item is the fixture itself (repeated)
    # and contains a "bookmakers" list. So, a single page is typical here.
    data = _make_api_request("odds", params=params)

    if not data or not data.get("response"):
        logger.warning(f"No odds data received or error in API request for fixture {fixture_api_id} with params {params}.")
        return
    
    # Expect data['response'] to be a list, often with one item for the requested fixture.
    api_response_odds_list = data.get("response", [])
    if not isinstance(api_response_odds_list, list):
        logger.error(f"API 'response' for odds is not a list. Received: {type(api_response_odds_list)}. Params: {params}")
        return
    
    if not api_response_odds_list:
        logger.info(f"Empty 'response' list for odds for fixture {fixture_api_id}.")
        return

    odds_markets_created = 0
    odds_markets_updated = 0
    odds_outcomes_created = 0
    odds_outcomes_updated = 0

    # Iterate through the response items (usually one for the fixture)
    for odds_fixture_item in api_response_odds_list:
        if not isinstance(odds_fixture_item, dict):
            logger.warning(f"Skipping odds item, not a dictionary: {odds_fixture_item}")
            continue
            
        api_odds_update_time = parse_datetime_from_api(odds_fixture_item.get("update"), "odds.update_timestamp")

        for bookmaker_data in odds_fixture_item.get("bookmakers", []):
            if not isinstance(bookmaker_data, dict):
                logger.warning(f"Skipping bookmaker data, not a dictionary: {bookmaker_data}")
                continue

            bookie_api_id = bookmaker_data.get("id")
            bookie_name = bookmaker_data.get("name", "Unknown Bookmaker")
            if not bookie_api_id:
                logger.warning(f"Skipping bookmaker due to missing ID: {bookmaker_data} for fixture {fixture_api_id}")
                continue

            try:
                bookmaker_obj, _ = Bookmaker.objects.update_or_create(
                    api_bookmaker_id=bookie_api_id,
                    defaults={'name': bookie_name}
                )

                for market_data_from_api in bookmaker_data.get("bets", []): # "bets" holds the markets
                    if not isinstance(market_data_from_api, dict):
                        logger.warning(f"Skipping market data, not a dictionary: {market_data_from_api}")
                        continue

                    market_name_api = market_data_from_api.get("name", "Unknown Market")
                    market_id_api = market_data_from_api.get("id") # API's ID for this market type

                    # Determine MarketCategory (can be pre-populated or created on-the-fly)
                    market_category_obj, _ = MarketCategory.objects.get_or_create(
                        name=market_name_api, # Or use a mapping if you have standardized category names
                        defaults={'description': f"API Market ID: {market_id_api if market_id_api else 'N/A'}"}
                    )
                    
                    # Parameterized markets (e.g., Over/Under 2.5, Handicap -1.5)
                    # This is complex and API-specific.
                    # `market_parameter` should be extracted if the market_name_api implies it.
                    # e.g. if market_name_api is "Total - Over/Under", the parameter is in `values.value` like "Over 2.5"
                    # For now, keeping it simple. Production code needs robust parsing here.
                    market_parameter_value = None # Placeholder: implement specific parsing logic

                    market_obj, m_created = Market.objects.update_or_create(
                        fixture=fixture_obj,
                        bookmaker=bookmaker_obj,
                        category=market_category_obj,
                        market_parameter=market_parameter_value,
                        defaults={
                            'is_active': True, # API might provide 'suspended' status for market
                            'last_updated_odds_api': api_odds_update_time
                        }
                    )
                    if m_created: odds_markets_created += 1
                    else: odds_markets_updated += 1
                    
                    outcomes_data = market_data_from_api.get("values", [])
                    if not isinstance(outcomes_data, list):
                        logger.warning(f"Market outcomes data is not a list: {outcomes_data}")
                        continue

                    for outcome_data in outcomes_data:
                        if not isinstance(outcome_data, dict):
                            logger.warning(f"Skipping outcome data, not a dictionary: {outcome_data}")
                            continue
                        outcome_name_api = outcome_data.get("value") # e.g., "Home", "Draw", "Over 2.5"
                        outcome_odds_api = outcome_data.get("odd")
                        
                        if outcome_name_api is None or outcome_odds_api is None:
                            logger.warning(f"Skipping outcome due to missing name or odds: {outcome_data} for market {market_name_api}, fixture {fixture_api_id}")
                            continue
                        try:
                            decimal_odds_val = float(str(outcome_odds_api).strip()) # Ensure string and strip spaces before float
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid odds format '{outcome_odds_api}' for outcome '{outcome_name_api}'. Skipping.")
                            continue

                        _, out_created = MarketOutcome.objects.update_or_create(
                            market=market_obj,
                            outcome_name=outcome_name_api, # This should uniquely identify outcome within the market
                            defaults={'odds': decimal_odds_val, 'is_suspended': False} # API might have suspension status per outcome
                        )
                        if out_created: odds_outcomes_created +=1
                        else: odds_outcomes_updated +=1
            except Exception as e:
                logger.error(f"Error processing odds for bookmaker {bookie_api_id} (Name: {bookie_name}), fixture {fixture_api_id}: {e}", exc_info=True)

    logger.info(f"Odds for fixture {fixture_api_id}: {odds_markets_created} markets created/updated, {odds_outcomes_created + odds_outcomes_updated} outcomes processed.")


# --- Orchestration Example ---
def run_full_data_update_for_leagues(league_api_ids, current_season_year, fetch_odds=True):
    """
    Orchestrates fetching leagues, teams, fixtures, and optionally odds.
    :param league_api_ids: List of API IDs for leagues to process.
    :param current_season_year: The season year (e.g., 2023).
    :param fetch_odds: Boolean, whether to fetch odds for upcoming fixtures.
    """
    if not isinstance(league_api_ids, list):
        logger.error("run_full_data_update_for_leagues expects league_api_ids to be a list.")
        return
    if not league_api_ids:
        logger.info("No league IDs provided for full data update.")
        return

    logger.info(f"--- Starting Full Data Update for Leagues: {league_api_ids}, Season: {current_season_year} ---")

    fetch_and_update_leagues(league_ids=league_api_ids, season=current_season_year)
    # Add a delay after a potentially large batch of API calls
    time.sleep(API_CALL_DELAY_SECONDS * 2) # Longer delay after all leagues are fetched

    # Ensure we operate on known leagues from DB that were requested
    leagues_to_process = League.objects.filter(api_league_id__in=league_api_ids)
    if not leagues_to_process.exists():
        logger.warning(f"None of the requested league IDs ({league_api_ids}) were found or created in the database. Aborting further processing for them.")
        return

    for league in leagues_to_process:
        logger.info(f"\nProcessing League: {league.name} (API ID: {league.api_league_id}) for season {current_season_year}")
        fetch_and_update_teams_for_league_season(league.api_league_id, current_season_year)
        time.sleep(API_CALL_DELAY_SECONDS)

        # Fetch all fixtures for the season. For production, consider date ranges for active fetching.
        logger.info(f"Fetching fixtures for league {league.name}, season {current_season_year}")
        fetch_and_update_fixtures(league_api_id=league.api_league_id, season_year=current_season_year)
        time.sleep(API_CALL_DELAY_SECONDS * 2) # Longer delay after all fixtures for a league

        if fetch_odds:
            # Fetch odds for recent/upcoming fixtures of this league
            # Example: Fixtures not yet started. Limit to a reasonable number per run.
            from django.utils import timezone as django_timezone # Django's timezone
            
            # Define statuses for "Not Started" or "To Be Defined" according to api-football documentation
            # Common examples: NS (Not Started), TBD (To Be Decided), PST (Postponed but might get odds)
            pending_statuses = ['NS', 'TBD', 'PST'] 
            
            fixtures_for_odds = FootballFixture.objects.filter(
                league=league,
                status_short__in=pending_statuses,
                match_date__gte=django_timezone.now() # Only future or very recent postponed games
            ).order_by('match_date')[:20] # Sensible limit to avoid excessive API calls

            logger.info(f"Found {fixtures_for_odds.count()} upcoming/pending fixtures in league {league.name} to fetch odds for.")
            for fixture in fixtures_for_odds:
                logger.info(f"Fetching odds for fixture: {fixture} (API ID: {fixture.match_api_id})")
                fetch_and_update_odds_for_fixture(fixture.match_api_id)
                time.sleep(API_CALL_DELAY_SECONDS) # Crucial delay between each fixture's odds fetch

    logger.info(f"--- Full Data Update for Leagues: {league_api_ids} Attempt Completed ---")