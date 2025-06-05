import requests
import time
import logging
from datetime import datetime, timezone
from django.conf import settings
from django.db import transaction
from dateutil import parser as dateutil_parser # For flexible date parsing (pip install python-dateutil)

# Import your models from the football_data_app
from .models import (
    League, Team, FootballFixture, Bookmaker,
    MarketCategory, Market, MarketOutcome
)

# --- Setup Logging ---
logger = logging.getLogger(__name__)

# --- Configuration ---
API_BASE_URL = "https://v3.football.api-sports.io" # Confirm this from api-football docs
API_KEY = getattr(settings, 'API_FOOTBALL_KEY', None)
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io", # Confirm this
    'x-rapidapi-key': API_KEY
}
# Ensure API_CALL_DELAY_SECONDS is loaded as a float for time.sleep()
API_CALL_DELAY_SECONDS = float(getattr(settings, 'API_FOOTBALL_CALL_DELAY_SECONDS', 2.0))


# --- Helper Functions ---

def _make_api_request(endpoint, params=None, is_paginated_endpoint=False, page=None):
    """
    Helper function to make requests to the api-football API.
    'page' parameter is only added if is_paginated_endpoint is True and page is not None.
    """
    if not API_KEY:
        logger.error("CRITICAL: API_FOOTBALL_KEY is not configured or is None in settings. Cannot make API calls.")
        return None

    url = f"{API_BASE_URL}/{endpoint}"
    current_params = params.copy() if params else {}

    if is_paginated_endpoint and page is not None:
        current_params['page'] = page
    elif 'page' in current_params and not is_paginated_endpoint: # Defensive: remove page if it was accidentally passed
        del current_params['page']

    try:
        logger.info(f"Attempting API request to URL: {url} with params: {current_params}")
        response = requests.get(url, headers=HEADERS, params=current_params, timeout=30) # 30 second timeout

        # Log basic response info before raising status, helpful for all responses
        logger.info(f"API Response Status for {url} | Params {current_params}: {response.status_code}")
        response_text_snippet = response.text[:1000] if response.text else "N/A" # First 1000 chars
        logger.info(f"API Response Text Snippet for {url} | Params {current_params}: {response_text_snippet}")

        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        response_data = response.json()

        # Check for errors field in the JSON response body from api-football
        if isinstance(response_data, dict) and response_data.get('errors'):
            api_errors = response_data['errors']
            # API errors can be a list or a string, or a dict
            if api_errors and ( (isinstance(api_errors, (list, dict)) and len(api_errors) > 0) or \
                                (isinstance(api_errors, str) and api_errors) ):
                # Handle the specific "page field do not exist" error carefully
                is_only_page_error = isinstance(api_errors, dict) and \
                                     api_errors.get('page') == "The Page field do not exist." and \
                                     len(api_errors) == 1

                if is_only_page_error and not is_paginated_endpoint:
                    # This warning occurs if 'page' was sent incorrectly by the calling function.
                    # The logic above should prevent 'page' from being in current_params here if is_paginated_endpoint is False.
                    logger.warning(f"API reported 'page field do not exist' for a query to {endpoint} with params {current_params}. This indicates 'page' might have been sent incorrectly for a non-paginated call.")
                    # Proceed, as the API might still return data despite this specific parameter error for non-paginated endpoints.
                elif not is_only_page_error: # If there are other errors, or it's a page error on an actual paginated call attempt
                    logger.error(f"API returned errors in JSON body: {api_errors} for URL: {url} with params: {current_params}")
                    return None # Hard fail for other API errors

        # Handle cases where API returns 200 OK, "results: 0", and empty "response": []
        # This often means the specific entity (e.g., league id for a season) was not found.
        if response_data.get("results") == 0 and not response_data.get("response") and \
           ('id' in current_params or 'ids' in current_params or 'fixture' in current_params): # for specific item lookups
            logger.warning(f"API for {url} with params {current_params} returned 0 results and empty response list. The specific ID/entity might not exist or has no data for the given parameters.")
            # Return the response_data so the calling function knows it's an empty valid response
            
        return response_data
    except requests.exceptions.HTTPError as http_err:
        # This block is hit if response.raise_for_status() triggers (4xx or 5xx client/server errors)
        # The status and response text were already logged above.
        logger.error(f"HTTPError ({http_err.response.status_code if http_err.response else 'N/A'}) caught in _make_api_request for {url} with params {current_params}.")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"ConnectionError occurred making API request to {url} with params {current_params}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"TimeoutError occurred making API request to {url} with params {current_params}: {timeout_err}")
    except requests.exceptions.RequestException as req_err: # Catch other requests-related errors
        logger.error(f"A general RequestException occurred during API request to {url} with params {current_params}: {req_err}")
    except ValueError as json_err: # Includes JSONDecodeError if response.json() fails
        logger.error(f"JSONDecodeError for API request to {url} with params {current_params}: {json_err}. Response Text was: {response_text_snippet if 'response_text_snippet' in locals() else 'Response text not captured'}")
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"An unexpected error occurred in _make_api_request for {url} with params {current_params}: {e}", exc_info=True)
    return None


def parse_datetime_from_api(datetime_str, field_name="datetime"):
    if datetime_str is None:
        return None
    try:
        if isinstance(datetime_str, (int, float)): # Unix timestamp
            return datetime.fromtimestamp(datetime_str, tz=timezone.utc if settings.USE_TZ else None)
        # ISO 8601 string
        dt_obj = dateutil_parser.isoparse(datetime_str)
        if settings.USE_TZ and dt_obj.tzinfo is None: # Ensure timezone awareness
             dt_obj = dt_obj.replace(tzinfo=timezone.utc) # Assume UTC if not specified
        return dt_obj
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse {field_name}: '{datetime_str}'. Error: {e}")
        return None

def _get_api_paging_info(response_data):
    if not isinstance(response_data, dict):
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
    logger.debug("Paging information not found or incomplete in API response's 'paging' dictionary.")
    return None, None

# --- Data Fetching and Processing Functions ---

@transaction.atomic
def fetch_and_update_leagues(league_ids=None, country_code=None, season=None):
    logger.info(f"Function fetch_and_update_leagues called. IDs: {league_ids}, Country: {country_code}, Season: {season}")
    params = {}
    is_specific_id_query = False # True if 'id' is used for a single league

    if league_ids:
        if isinstance(league_ids, list) and len(league_ids) == 1:
            params['id'] = str(league_ids[0]) # API might expect string ID
            is_specific_id_query = True
        elif isinstance(league_ids, (int, str)):
            params['id'] = str(league_ids)
            is_specific_id_query = True
        elif isinstance(league_ids, list) and len(league_ids) > 1:
            logger.info(f"Fetching multiple specific league IDs ({len(league_ids)}) by iterating individual calls.")
            for lid in league_ids: # API /leagues usually doesn't take a list of IDs, so iterate
                fetch_and_update_leagues(league_ids=[lid], country_code=country_code, season=season) # Recursive call
                time.sleep(API_CALL_DELAY_SECONDS)
            return # Return after iterating
    
    # General query parameters
    if country_code: params['country'] = country_code
    if season: params['season'] = str(season) # API might expect string season

    # Determine if pagination is expected for this call
    # If 'id' is in params, it's a specific league lookup, typically not paginated by the API.
    # Otherwise (e.g., by country, or all leagues for a season), it is paginated.
    is_paginated_call = not is_specific_id_query

    current_page = 1
    total_pages = 1 # Assume 1 page initially unless pagination info says otherwise
    all_league_data_wrappers = []

    while current_page <= total_pages:
        page_to_send = current_page if is_paginated_call else None
        logger.info(f"Fetching leagues page {current_page} of {total_pages} with params {params} (is_paginated: {is_paginated_call}, page_param: {page_to_send})...")
        data = _make_api_request("leagues", params=params, is_paginated_endpoint=is_paginated_call, page=page_to_send)
        
        if not data: # _make_api_request already logged the specific error
            logger.error(f"Failed to fetch leagues (page {current_page}) for params: {params}. _make_api_request returned None.")
            if is_specific_id_query or not is_paginated_call : return # Abort for this specific ID or if first page of general query fails
            else: break # For paginated general query, stop trying further pages

        api_response_leagues = data.get("response", [])
        if not isinstance(api_response_leagues, list):
            logger.error(f"API 'response' for leagues is not a list as expected. Received: {type(api_response_leagues)}. Params: {params}")
            if is_specific_id_query or not is_paginated_call : return
            else: break

        if not api_response_leagues: # Empty "response" list
            logger.info(f"No league data in 'response' on page {current_page} for params: {params}.")
            if is_specific_id_query or not is_paginated_call: # If it was specific ID or first page, means not found or empty.
                 logger.warning(f"League with params {params} not found or API returned empty response list for this attempt.")
            break 

        all_league_data_wrappers.extend(api_response_leagues)

        if is_paginated_call:
            if current_page == 1: # Check total pages only on the first successful page of a paginated call
                current_page_from_api, total_pages_from_api = _get_api_paging_info(data)
                if total_pages_from_api is not None:
                    total_pages = total_pages_from_api
                    logger.info(f"Total pages for leagues query: {total_pages}")
                    # API-Football sometimes returns current_page > total_pages if page param is invalid, so check
                    if current_page_from_api is not None and current_page_from_api > total_pages:
                        logger.warning(f"API returned current_page ({current_page_from_api}) > total_pages ({total_pages}). Assuming no more pages.")
                        break
                else: # No valid paging info
                    logger.info("No valid paging info for leagues; assuming single page for this paginated call.")
                    break 
            if current_page >= total_pages:
                break
            current_page += 1
            if current_page <= total_pages: # Only sleep if there's another page to fetch
                time.sleep(API_CALL_DELAY_SECONDS)
        else: # If not a paginated call (e.g., by specific ID), break after the first (and only) attempt
            break
            
    leagues_created_count = 0; leagues_updated_count = 0
    for league_data_wrapper in all_league_data_wrappers:
        try:
            if not isinstance(league_data_wrapper, dict): logger.warning(f"Skipping league entry, not a dict: {league_data_wrapper}"); continue
            league_info = league_data_wrapper.get("league")
            country_info = league_data_wrapper.get("country")
            if not isinstance(league_info, dict) or not league_info.get("id"): logger.warning(f"Skipping league, missing ID/data: {league_data_wrapper}"); continue
            
            defaults = {
                'name': league_info.get("name", "N/A"),
                'logo_url': league_info.get("logo"),
            }
            if isinstance(country_info, dict) and country_info.get("name"): # Ensure country_info and its name exist
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
    if not all_league_data_wrappers and (params): # If specific params were given and nothing was processed
        logger.warning(f"No league data was successfully processed for input params: {params}")


@transaction.atomic
def fetch_and_update_teams_for_league_season(league_api_id, season_year):
    logger.info(f"Function fetch_and_update_teams_for_league_season called for league API ID {league_api_id}, season {season_year}")
    try:
        League.objects.get(api_league_id=league_api_id)
    except League.DoesNotExist:
        logger.error(f"League with api_league_id {league_api_id} not found in DB. Cannot fetch teams.")
        return

    params = {'league': str(league_api_id), 'season': str(season_year)}
    # The /teams endpoint when filtered by league and season IS typically paginated by api-football
    is_paginated_call = True 

    current_page = 1; total_pages = 1; all_team_data_wrappers = []
    while current_page <= total_pages:
        logger.info(f"Fetching teams page {current_page} of {total_pages} for league {league_api_id}, season {season_year}...")
        data = _make_api_request("teams", params=params, is_paginated_endpoint=is_paginated_call, page=current_page)
        
        if not data:
            logger.error(f"Failed to fetch teams page {current_page} for league {league_api_id}, season {season_year}. _make_api_request returned None.")
            break 

        api_response_teams = data.get("response", [])
        if not isinstance(api_response_teams, list):
            logger.error(f"API 'response' for teams is not a list. Received: {type(api_response_teams)}. Params: {params}"); break
        if not api_response_teams:
            logger.info(f"No team data in 'response' on page {current_page} for league {league_api_id}, season {season_year}."); break
        
        all_team_data_wrappers.extend(api_response_teams)

        if current_page == 1:
            _, total_pages_from_api = _get_api_paging_info(data)
            if total_pages_from_api is not None: total_pages = total_pages_from_api; logger.info(f"Total pages for teams in league {league_api_id}: {total_pages}")
            else: logger.info("No valid paging info for teams; assuming single page."); break
        
        if current_page >= total_pages: break
        current_page += 1
        if current_page <= total_pages: time.sleep(API_CALL_DELAY_SECONDS)
    
    teams_created_count = 0; teams_updated_count = 0
    for team_data_wrapper in all_team_data_wrappers:
        try:
            if not isinstance(team_data_wrapper, dict): logger.warning(f"Skipping team entry, not a dict: {team_data_wrapper}"); continue
            team_info = team_data_wrapper.get("team")
            if not isinstance(team_info, dict) or not team_info.get("id"): logger.warning(f"Skipping team, missing ID/data: {team_data_wrapper}"); continue
            defaults = {
                'name': team_info.get("name", "N/A"), 'code': team_info.get("code"),
                'logo_url': team_info.get("logo"), 'country': team_info.get("country"),
            }
            _, created = Team.objects.update_or_create(api_team_id=team_info["id"], defaults=defaults)
            if created: teams_created_count += 1
            else: teams_updated_count +=1
        except Exception as e:
            logger.error(f"Error processing team data: {team_data_wrapper}. Error: {e}", exc_info=True)
    logger.info(f"Teams for league {league_api_id}, season {season_year} fetch complete: {teams_created_count} created, {teams_updated_count} updated.")


@transaction.atomic
def fetch_and_update_fixtures(league_api_id=None, season_year=None, date_from_str=None, date_to_str=None, fixture_api_ids=None):
    logger.info(f"Function fetch_and_update_fixtures called. League: {league_api_id}, Season: {season_year}, Dates: {date_from_str}-{date_to_str}, IDs: {fixture_api_ids}")
    params = {}
    is_query_by_specific_ids = False # True if 'id' or 'ids' is used

    if fixture_api_ids:
        is_query_by_specific_ids = True
        if isinstance(fixture_api_ids, list) and len(fixture_api_ids) == 1:
            params['id'] = str(fixture_api_ids[0])
        elif isinstance(fixture_api_ids, (int, str)):
            params['id'] = str(fixture_api_ids)
        elif isinstance(fixture_api_ids, list) and len(fixture_api_ids) > 1:
            # API-Football /fixtures endpoint supports multiple IDs via 'ids' parameter (e.g., "id1-id2-id3")
            params['ids'] = '-'.join(map(str, fixture_api_ids))
    else:
        if league_api_id: params['league'] = str(league_api_id)
        if season_year: params['season'] = str(season_year)
        if date_from_str: params['from'] = date_from_str
        if date_to_str: params['to'] = date_to_str
        if date_from_str and not date_to_str and 'from' not in params: params['date'] = date_from_str
    
    if not params:
        logger.warning("Fixture fetch called without any identifying parameters. Aborting.")
        return

    # Paginate if not querying by specific 'id' or 'ids'.
    # Queries by specific IDs (single 'id' or multiple 'ids') are typically NOT paginated by the API.
    is_paginated_call = not is_query_by_specific_ids

    current_page = 1; total_pages = 1; all_fixture_data_wrappers = []
    while current_page <= total_pages:
        page_to_send = current_page if is_paginated_call else None
        logger.info(f"Fetching fixtures page {current_page} of {total_pages} with params {params} (is_paginated: {is_paginated_call}, page_param: {page_to_send})...")
        data = _make_api_request("fixtures", params=params, is_paginated_endpoint=is_paginated_call, page=page_to_send)
        
        if not data:
            logger.error(f"Failed to fetch fixtures (page {current_page}) for params: {params}. _make_api_request returned None.")
            if is_query_by_specific_ids or not is_paginated_call : return
            else: break

        api_response_fixtures = data.get("response", [])
        if not isinstance(api_response_fixtures, list):
            logger.error(f"API 'response' for fixtures not a list. Params: {params}");
            if is_query_by_specific_ids or not is_paginated_call : return
            else: break
        
        if not api_response_fixtures:
            logger.info(f"No fixture data in 'response' on page {current_page} for params: {params}")
            if is_query_by_specific_ids or not is_paginated_call:
                 logger.warning(f"Fixture(s) with params {params} not found or API returned empty response.")
            break

        all_fixture_data_wrappers.extend(api_response_fixtures)

        if is_paginated_call:
            if current_page == 1:
                _, total_pages_from_api = _get_api_paging_info(data)
                if total_pages_from_api is not None: total_pages = total_pages_from_api; logger.info(f"Total pages for fixtures: {total_pages}")
                else: logger.info("No paging info for fixtures; assuming single page."); break
            if current_page >= total_pages: break
            current_page += 1
            if current_page <= total_pages: time.sleep(API_CALL_DELAY_SECONDS)
        else: # If not a paginated call (by ID/IDs), break after the first attempt
            break
            
    fixtures_created = 0; fixtures_updated = 0
    for fixture_data in all_fixture_data_wrappers:
        try:
            if not isinstance(fixture_data, dict): logger.warning(f"Skipping fixture entry, not dict: {fixture_data}"); continue
            fix_info = fixture_data.get("fixture", {}); league_info = fixture_data.get("league", {})
            teams_data = fixture_data.get("teams", {}); home_team_info = teams_data.get("home", {}); away_team_info = teams_data.get("away", {})
            goals_info = fixture_data.get("goals", {}); score_info = fixture_data.get("score", {})
            
            fixture_api_id_val = fix_info.get("id"); league_api_id_val = league_info.get("id")
            home_team_api_id_val = home_team_info.get("id"); away_team_api_id_val = away_team_info.get("id")

            if not all([fixture_api_id_val, league_api_id_val, home_team_api_id_val, away_team_api_id_val]):
                logger.warning(f"Skipping fixture due to missing critical IDs. Data: {fixture_data}"); continue
            
            match_api_id_str = str(fixture_api_id_val)
            league_obj = League.objects.filter(api_league_id=league_api_id_val).first()
            home_team_obj = Team.objects.filter(api_team_id=home_team_api_id_val).first()
            away_team_obj = Team.objects.filter(api_team_id=away_team_api_id_val).first()

            if not league_obj: logger.warning(f"League {league_api_id_val} not found for fixture {match_api_id_str}.")
            if not home_team_obj: logger.warning(f"Home team {home_team_api_id_val} not found for fixture {match_api_id_str}.")
            if not away_team_obj: logger.warning(f"Away team {away_team_api_id_val} not found for fixture {match_api_id_str}.")
            
            fixture_defaults = {
                'league': league_obj, 'home_team': home_team_obj, 'away_team': away_team_obj,
                'match_date': parse_datetime_from_api(fix_info.get("date"), "fixture.date"),
                'status_short': fix_info.get("status", {}).get("short", "N/A"),
                'status_long': fix_info.get("status", {}).get("long", "Not Available"),
                'venue_name': fix_info.get("venue", {}).get("name"), 'referee': fix_info.get("referee"),
                'round': league_info.get("round"), 'home_team_score': goals_info.get("home"),
                'away_team_score': goals_info.get("away"),
                'halftime_home_score': score_info.get("halftime", {}).get("home"),
                'halftime_away_score': score_info.get("halftime", {}).get("away"),
                'extratime_home_score': score_info.get("extratime", {}).get("home"),
                'extratime_away_score': score_info.get("extratime", {}).get("away"),
                'penalty_home_score': score_info.get("penalty", {}).get("home"),
                'penalty_away_score': score_info.get("penalty", {}).get("away"),
                'api_fixture_timestamp': parse_datetime_from_api(fix_info.get("timestamp"), "fixture.timestamp"),
                'is_result_confirmed': fix_info.get("status", {}).get("short") in ["FT", "AET", "PEN", "AWDD", "ABD", "WO"]
            }
            _, created = FootballFixture.objects.update_or_create(match_api_id=match_api_id_str, defaults=fixture_defaults)
            if created: fixtures_created += 1
            else: fixtures_updated += 1
        except Exception as e:
            logger.error(f"Error processing fixture data: {fixture_data}. Error: {e}", exc_info=True)
    logger.info(f"Fixtures fetch complete: {fixtures_created} created, {fixtures_updated} updated from {len(all_fixture_data_wrappers)} API entries.")


@transaction.atomic
def fetch_and_update_odds_for_fixture(fixture_api_id, bookmaker_api_id_filter=None):
    logger.info(f"Function fetch_and_update_odds_for_fixture called for fixture API ID {fixture_api_id}, Bookmaker filter: {bookmaker_api_id_filter}")
    try:
        fixture_obj = FootballFixture.objects.get(match_api_id=str(fixture_api_id))
    except FootballFixture.DoesNotExist:
        logger.error(f"Fixture with match_api_id {fixture_api_id} not found. Cannot fetch odds.")
        return

    params = {'fixture': str(fixture_api_id)}
    if bookmaker_api_id_filter:
        params['bookmaker'] = str(bookmaker_api_id_filter)

    # The /odds endpoint for a specific fixture ID is typically NOT paginated.
    # It returns all bookmakers/markets for that single fixture in one response.
    is_paginated_call_odds = False
    data = _make_api_request("odds", params=params, is_paginated_endpoint=is_paginated_call_odds, page=None)

    if not data or not data.get("response"):
        logger.warning(f"No odds data received or error in API request for fixture {fixture_api_id} with params {params}.")
        return
    
    api_response_odds_list = data.get("response", [])
    if not isinstance(api_response_odds_list, list):
        logger.error(f"API 'response' for odds is not a list. Received: {type(api_response_odds_list)}. Params: {params}"); return
    if not api_response_odds_list:
        logger.info(f"Empty 'response' list for odds for fixture {fixture_api_id}."); return

    odds_markets_created = 0; odds_markets_updated = 0; odds_outcomes_created = 0; odds_outcomes_updated = 0
    for odds_fixture_item in api_response_odds_list: # Usually one item containing list of bookmakers
        if not isinstance(odds_fixture_item, dict): logger.warning(f"Skipping odds item, not dict: {odds_fixture_item}"); continue
        api_odds_update_time = parse_datetime_from_api(odds_fixture_item.get("update"), "odds.update_timestamp")
        
        for bookmaker_data in odds_fixture_item.get("bookmakers", []):
            if not isinstance(bookmaker_data, dict): logger.warning(f"Skipping bookmaker data, not dict: {bookmaker_data}"); continue
            bookie_api_id = bookmaker_data.get("id"); bookie_name = bookmaker_data.get("name", "Unknown Bookmaker")
            if not bookie_api_id: logger.warning(f"Skipping bookmaker, missing ID: {bookmaker_data}"); continue
            try:
                bookmaker_obj, _ = Bookmaker.objects.update_or_create(api_bookmaker_id=bookie_api_id, defaults={'name': bookie_name})
                for market_data_api in bookmaker_data.get("bets", []): # 'bets' holds markets
                    if not isinstance(market_data_api, dict): logger.warning(f"Skipping market data, not dict: {market_data_api}"); continue
                    market_name_api = market_data_api.get("name", "Unknown Market"); market_id_api = market_data_api.get("id")
                    market_category_obj, _ = MarketCategory.objects.get_or_create(name=market_name_api, defaults={'description': f"API Market ID: {market_id_api if market_id_api else 'N/A'}"})
                    market_parameter_value = None # TODO: Implement robust parsing logic for parameterized markets (e.g., Over/Under values)
                    
                    market_obj, m_created = Market.objects.update_or_create(
                        fixture=fixture_obj, bookmaker=bookmaker_obj, category=market_category_obj, market_parameter=market_parameter_value,
                        defaults={'is_active': True, 'last_updated_odds_api': api_odds_update_time}
                    )
                    if m_created: odds_markets_created += 1
                    else: odds_markets_updated += 1
                    
                    outcomes_data = market_data_api.get("values", []) # 'values' holds outcomes
                    if not isinstance(outcomes_data, list): logger.warning(f"Market outcomes data not a list for market '{market_name_api}': {outcomes_data}"); continue
                    for outcome_data in outcomes_data:
                        if not isinstance(outcome_data, dict): logger.warning(f"Skipping outcome, not dict: {outcome_data}"); continue
                        outcome_name_api = outcome_data.get("value"); outcome_odds_api = outcome_data.get("odd")
                        if outcome_name_api is None or outcome_odds_api is None: logger.warning(f"Skipping outcome, missing name/odds: {outcome_data}"); continue
                        try: decimal_odds_val = float(str(outcome_odds_api).strip())
                        except (ValueError, TypeError): logger.warning(f"Invalid odds format '{outcome_odds_api}' for outcome '{outcome_name_api}'. Skipping."); continue
                        _, out_created = MarketOutcome.objects.update_or_create(
                            market=market_obj, outcome_name=outcome_name_api,
                            defaults={'odds': decimal_odds_val, 'is_suspended': False} # API might indicate suspension
                        )
                        if out_created: odds_outcomes_created +=1
                        else: odds_outcomes_updated +=1
            except Exception as e:
                logger.error(f"Error processing odds for bookmaker {bookie_api_id} (Name: {bookie_name}), fixture {fixture_api_id}: {e}", exc_info=True)
    logger.info(f"Odds for fixture {fixture_api_id}: {odds_markets_created} markets created/updated, {odds_outcomes_created + odds_outcomes_updated} outcomes processed.")

def run_full_data_update_for_leagues(league_api_ids, current_season_year, fetch_odds=True):
    """
    Orchestrates fetching leagues, teams, fixtures, and optionally odds.
    """
    if not isinstance(league_api_ids, list):
        logger.error("run_full_data_update_for_leagues expects league_api_ids to be a list.")
        return "Error: league_api_ids must be a list." # Return error message
    if not league_api_ids:
        logger.info("No league IDs provided for full data update.")
        return "No league IDs provided."

    logger.info(f"--- Starting Full Data Update for Leagues: {league_api_ids}, Season: {current_season_year} ---")

    # Fetch specified leagues first
    fetch_and_update_leagues(league_ids=league_api_ids, season=current_season_year)
    time.sleep(API_CALL_DELAY_SECONDS * 2) # Delay after potentially multiple league fetches

    # Process only the leagues that were successfully fetched/found or already in DB
    leagues_to_process = League.objects.filter(api_league_id__in=[str(lid) for lid in league_api_ids]) # Ensure IDs are strings if necessary
    
    if not leagues_to_process.exists():
        logger.warning(f"None of the requested league IDs ({league_api_ids}) were found or created in the database after fetch attempt. Aborting further processing for them.")
        return f"No valid leagues found in DB for IDs: {league_api_ids} after fetch attempt."

    for league in leagues_to_process:
        logger.info(f"\nProcessing League: {league.name} (API ID: {league.api_league_id}) for season {current_season_year}")
        
        fetch_and_update_teams_for_league_season(league.api_league_id, current_season_year)
        time.sleep(API_CALL_DELAY_SECONDS)
        
        logger.info(f"Fetching fixtures for league {league.name}, season {current_season_year}")
        fetch_and_update_fixtures(league_api_id=league.api_league_id, season_year=current_season_year)
        time.sleep(API_CALL_DELAY_SECONDS * 2)

        if fetch_odds:
            # Fetch odds for recent/upcoming fixtures of this league
            pending_statuses = ['NS', 'TBD', 'PST'] # Not Started, To Be Defined, Postponed
            
            # Ensure match_date__gte uses timezone aware datetime if Django USE_TZ is True
            now_aware = django_timezone.now() if settings.USE_TZ else datetime.now()

            fixtures_for_odds = FootballFixture.objects.filter(
                league=league, 
                status_short__in=pending_statuses, 
                match_date__gte=now_aware 
            ).order_by('match_date')[:20] # Limit API calls per run

            logger.info(f"Found {fixtures_for_odds.count()} upcoming/pending fixtures in league {league.name} to fetch odds for.")
            for fixture in fixtures_for_odds:
                logger.info(f"Fetching odds for fixture: {fixture} (API ID: {fixture.match_api_id})")
                fetch_and_update_odds_for_fixture(fixture.match_api_id)
                time.sleep(API_CALL_DELAY_SECONDS) # Crucial delay
    
    logger.info(f"--- Full Data Update for Leagues: {league_api_ids} Attempt Completed ---")
    return f"Full data update for leagues {league_api_ids} completed."

