import requests
import time
import logging
from datetime import datetime, timezone # Standard library
from django.conf import settings
from django.db import transaction
from dateutil import parser as dateutil_parser # pip install python-dateutil
from django.utils import timezone as django_timezone # Django's timezone utilities

# Import your models from the football_data_app
from .models import (
    League, Team, FootballFixture, Bookmaker,
    MarketCategory, Market, MarketOutcome
)

# --- Setup Logging ---
logger = logging.getLogger(__name__)

# --- Configuration ---
API_BASE_URL = "https://v3.football.api-sports.io"
API_KEY = getattr(settings, 'API_FOOTBALL_KEY', None)
HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_KEY
}
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
    elif 'page' in current_params and not is_paginated_endpoint:
        # Defensively remove 'page' if the call isn't supposed to be paginated by this param
        del current_params['page']

    try:
        logger.info(f"Attempting API request to URL: {url} with params: {current_params}")
        response = requests.get(url, headers=HEADERS, params=current_params, timeout=30)

        logger.info(f"API Response Status for {url} | Params {current_params}: {response.status_code}")
        response_text_snippet = response.text[:1000] if response.text else "N/A"
        logger.info(f"API Response Text Snippet for {url} | Params {current_params}: {response_text_snippet}")

        response.raise_for_status()
        response_data = response.json()

        if isinstance(response_data, dict) and response_data.get('errors'):
            api_errors = response_data['errors']
            if api_errors and ( (isinstance(api_errors, (list, dict)) and len(api_errors) > 0) or \
                                (isinstance(api_errors, str) and api_errors) ):
                is_only_page_error = isinstance(api_errors, dict) and \
                                     api_errors.get('page') == "The Page field do not exist." and \
                                     len(api_errors) == 1
                
                if is_only_page_error:
                    logger.warning(f"API reported 'page field do not exist' for {url} with params {current_params}. This specific error about 'page' is noted. The endpoint/filter combination might not use the 'page' parameter as expected.")
                elif not is_only_page_error :
                    logger.error(f"API returned errors in JSON body: {api_errors} for URL: {url} with params: {current_params}")
                    return None
        
        if response_data.get("results") == 0 and not response_data.get("response") and \
           ('id' in current_params or 'ids' in current_params or 'fixture' in current_params):
            logger.warning(f"API for {url} with params {current_params} returned 0 results and empty response list (entity might not exist or no data for these specific parameters).")
            
        return response_data
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTPError ({http_err.response.status_code if http_err.response else 'N/A'}) caught for {url} with params {current_params}.")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"ConnectionError for {url} with params {current_params}: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"TimeoutError for {url} with params {current_params}: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"RequestException for {url} with params {current_params}: {req_err}")
    except ValueError as json_err: 
        logger.error(f"JSONDecodeError for {url} with params {current_params}: {json_err}. Response: {response_text_snippet if 'response_text_snippet' in locals() else 'Response text not captured'}")
    except Exception as e:
        logger.error(f"Unexpected error in _make_api_request for {url} with params {current_params}: {e}", exc_info=True)
    return None


def parse_datetime_from_api(datetime_str, field_name="datetime"):
    if datetime_str is None: 
        return None
    try:
        if isinstance(datetime_str, (int, float)):
            return datetime.fromtimestamp(datetime_str, tz=timezone.utc if settings.USE_TZ else None)
        dt_obj = dateutil_parser.isoparse(datetime_str)
        if settings.USE_TZ and dt_obj.tzinfo is None:
             dt_obj = dt_obj.replace(tzinfo=timezone.utc)
        return dt_obj
    except Exception as e: 
        logger.warning(f"Could not parse {field_name}: '{datetime_str}'. Error: {e}")
        return None

def _get_api_paging_info(response_data):
    if not isinstance(response_data, dict): 
        return None, None
    paging = response_data.get('paging')
    if paging and isinstance(paging, dict):
        current_page, total_pages = paging.get('current'), paging.get('total')
        if current_page is not None and total_pages is not None:
            try: 
                return int(current_page), int(total_pages)
            except Exception: 
                logger.warning(f"Could not parse paging info: {paging}")
    return None, None

@transaction.atomic
def fetch_and_update_leagues(league_ids=None, country_code=None, season=None):
    logger.info(f"Fn fetch_and_update_leagues: IDs:{league_ids}, Country:{country_code}, Season:{season}")
    params = {}; is_specific_id_query = False
    if league_ids:
        if isinstance(league_ids, list) and len(league_ids) == 1: 
            params['id'] = str(league_ids[0]); is_specific_id_query = True
        elif isinstance(league_ids, (int, str)): 
            params['id'] = str(league_ids); is_specific_id_query = True
        elif isinstance(league_ids, list) and len(league_ids) > 1:
            logger.info(f"Fetching multiple specific league IDs ({len(league_ids)}) by iterating individual calls.")
            for lid in league_ids: 
                fetch_and_update_leagues(league_ids=[lid], country_code=country_code, season=season)
                time.sleep(API_CALL_DELAY_SECONDS)
            return
    if country_code: params['country'] = country_code
    if season: params['season'] = str(season)
    
    is_paginated_call = not is_specific_id_query
    current_page = 1; total_pages = 1; all_league_data = []

    while current_page <= total_pages:
        page_to_send = current_page if is_paginated_call else None
        logger.info(f"Leagues P{current_page}/{total_pages} params:{params} paginated:{is_paginated_call} page_sent:{page_to_send}")
        data = _make_api_request("leagues", params=params, is_paginated_endpoint=is_paginated_call, page=page_to_send)
        
        if not data: 
            logger.error(f"Failed leagues p{current_page} params:{params}. No data received from API.")
            if is_specific_id_query: return # If specific ID query fails, abort for this ID
            else: break # For general query, stop trying further pages
        
        api_response = data.get("response", [])
        if not isinstance(api_response, list): 
            logger.error(f"Leagues API 'response' not list. Params:{params}")
            if is_specific_id_query: return
            else: break
            
        if not api_response: 
            logger.info(f"No league data in 'response' p{current_page} params:{params}")
            break
        
        all_league_data.extend(api_response)
        if is_paginated_call:
            if current_page == 1:
                current_page_from_api, total_pages_from_api = _get_api_paging_info(data)
                if total_pages_from_api is not None:
                    total_pages = total_pages_from_api
                    logger.info(f"Total pages for leagues query: {total_pages}")
                    if current_page_from_api is not None and current_page_from_api > total_pages:
                        logger.warning(f"API returned current_page ({current_page_from_api}) > total_pages ({total_pages}). Correcting and breaking.")
                        break
                else: 
                    logger.info("No valid paging info for leagues; assuming single page for this paginated call.")
                    break 
            if current_page >= total_pages: 
                break
            current_page += 1
            if current_page <= total_pages: 
                time.sleep(API_CALL_DELAY_SECONDS)
        else: 
            break 
            
    created_c = 0; updated_c = 0
    for item in all_league_data:
        try:
            if not isinstance(item, dict): 
                logger.warning(f"Skip league, not dict: {item}")
                continue
            li = item.get("league"); ci = item.get("country")
            if not isinstance(li, dict) or not li.get("id"): 
                logger.warning(f"Skip league, no ID/data: {item}")
                continue
            defs = {'name': li.get("name", "N/A"), 'logo_url': li.get("logo")}
            if isinstance(ci, dict) and ci.get("name"): 
                defs['country'] = ci.get("name")
            
            _, created = League.objects.update_or_create(api_league_id=li["id"], defaults=defs)
            if created: 
                created_c += 1
            else: 
                updated_c +=1
        except Exception as e: 
            logger.error(f"Error processing league: {item}. E: {e}", exc_info=True)
    logger.info(f"Leagues: {created_c} created, {updated_c} updated from {len(all_league_data)} API entries.")
    if not all_league_data and params: 
        logger.warning(f"No leagues were successfully processed for input params: {params}")

@transaction.atomic
def fetch_and_update_teams_for_league_season(league_api_id, season_year):
    logger.info(f"Fn fetch_teams: LeagueID:{league_api_id}, Season:{season_year}")
    try: 
        League.objects.get(api_league_id=league_api_id)
    except League.DoesNotExist: 
        logger.error(f"League {league_api_id} not in DB. Cannot fetch teams.")
        return
        
    params = {'league': str(league_api_id), 'season': str(season_year)}
    is_paginated_call = False # Assumed not paginated by 'page' for this filter based on API errors
    
    current_page = 1; total_pages = 1; all_team_data = []
    while current_page <= total_pages:
        page_to_send = None # Not sending page for this specific call type
        logger.info(f"Teams P{current_page}/{total_pages} L:{league_api_id} S:{season_year} paginated:{is_paginated_call} page_sent:{page_to_send}")
        data = _make_api_request("teams", params=params, is_paginated_endpoint=is_paginated_call, page=page_to_send)
        
        if not data: 
            logger.error(f"Failed teams p{current_page} L:{league_api_id} S:{season_year}. No data.")
            break
            
        api_response = data.get("response", [])
        if not isinstance(api_response, list): 
            logger.error(f"Teams API 'response' not list. Params:{params}")
            break
            
        if not api_response: 
            logger.info(f"No team data in 'response' p{current_page} L:{league_api_id} S:{season_year}")
            break
            
        all_team_data.extend(api_response)
        
        if is_paginated_call: # This block currently won't be hit if is_paginated_call is False
            if current_page == 1:
                _, tp_api = _get_api_paging_info(data)
                if tp_api is not None: 
                    total_pages = tp_api
                    logger.info(f"Total pages for teams L:{league_api_id}: {total_pages}")
                else: 
                    logger.info("No paging for teams; assuming 1 page.")
                    break
            if current_page >= total_pages: 
                break
            current_page += 1
            if current_page <= total_pages: 
                time.sleep(API_CALL_DELAY_SECONDS)
        else: 
            break 
            
    created_c = 0; updated_c = 0
    for item in all_team_data:
        try:
            if not isinstance(item, dict): 
                logger.warning(f"Skip team, not dict: {item}")
                continue
            ti = item.get("team")
            if not isinstance(ti, dict) or not ti.get("id"): 
                logger.warning(f"Skip team, no ID/data: {item}")
                continue
            defs = {'name': ti.get("name", "N/A"), 'code': ti.get("code"), 
                    'logo_url': ti.get("logo"), 'country': ti.get("country")}
            _, created = Team.objects.update_or_create(api_team_id=ti["id"], defaults=defs)
            if created: 
                created_c += 1
            else: 
                updated_c +=1
        except Exception as e: 
            logger.error(f"Error processing team: {item}. E: {e}", exc_info=True)
    logger.info(f"Teams L:{league_api_id} S:{season_year}: {created_c} created, {updated_c} updated from {len(all_team_data)}.")

@transaction.atomic
def fetch_and_update_fixtures(league_api_id=None, season_year=None, date_from_str=None, date_to_str=None, fixture_api_ids=None):
    logger.info(f"Fn fetch_fixtures: L:{league_api_id} S:{season_year} Dates:{date_from_str}-{date_to_str} IDs:{fixture_api_ids}")
    params = {}; is_query_by_specific_ids = False
    if fixture_api_ids:
        is_query_by_specific_ids = True
        if isinstance(fixture_api_ids, list) and len(fixture_api_ids) == 1: 
            params['id'] = str(fixture_api_ids[0])
        elif isinstance(fixture_api_ids, (int, str)): 
            params['id'] = str(fixture_api_ids)
        elif isinstance(fixture_api_ids, list) and len(fixture_api_ids) > 1: 
            params['ids'] = '-'.join(map(str, fixture_api_ids))
    else:
        if league_api_id: params['league'] = str(league_api_id)
        if season_year: params['season'] = str(season_year)
        if date_from_str: params['from'] = date_from_str
        if date_to_str: params['to'] = date_to_str
        if date_from_str and not date_to_str and 'from' not in params: 
            params['date'] = date_from_str
            
    if not params: 
        logger.warning("Fixture fetch no params. Aborting.")
        return
    
    is_paginated_call = not is_query_by_specific_ids
    if 'league' in params and 'season' in params and not is_query_by_specific_ids and \
       not ('from' in params or 'to' in params or 'date' in params):
         is_paginated_call = False
         logger.info(f"Querying all fixtures for league/season ({params}). Forcing is_paginated_call to False for 'page' parameter based on API behavior.")

    current_page = 1; total_pages = 1; all_fixture_data = []
    while current_page <= total_pages:
        page_to_send = current_page if is_paginated_call else None
        logger.info(f"Fixtures P{current_page}/{total_pages} params:{params} paginated:{is_paginated_call} page_sent:{page_to_send}")
        data = _make_api_request("fixtures", params=params, is_paginated_endpoint=is_paginated_call, page=page_to_send)
        
        if not data: 
            logger.error(f"Failed fixtures p{current_page} params:{params}. No data.")
            if is_query_by_specific_ids: return
            else: break
            
        api_response = data.get("response", [])
        if not isinstance(api_response, list): 
            logger.error(f"Fixtures API 'response' not list. Params:{params}")
            if is_query_by_specific_ids: return
            else: break
            
        if not api_response: 
            logger.info(f"No fixture data in 'response' p{current_page} params:{params}")
            break
            
        all_fixture_data.extend(api_response)
        if is_paginated_call:
            if current_page == 1:
                _, tp_api = _get_api_paging_info(data)
                if tp_api is not None: 
                    total_pages = tp_api
                    logger.info(f"Total pages for fixtures: {total_pages}")
                else: 
                    logger.info("No paging for fixtures; assuming 1 page.")
                    break
            if current_page >= total_pages: 
                break
            current_page += 1
            if current_page <= total_pages: 
                time.sleep(API_CALL_DELAY_SECONDS)
        else: 
            break
            
    created_c = 0; updated_c = 0
    for item in all_fixture_data:
        try:
            if not isinstance(item, dict): 
                logger.warning(f"Skip fixture, not dict: {item}")
                continue
            fi = item.get("fixture", {}); li = item.get("league", {})
            td = item.get("teams", {}); hti = td.get("home", {}); ati = td.get("away", {})
            gi = item.get("goals", {}); si = item.get("score", {})
            fid = fi.get("id"); lid = li.get("id"); htid = hti.get("id"); atid = ati.get("id")
            if not all([fid, lid, htid, atid]): 
                logger.warning(f"Skip fixture, missing IDs. Data:{item}")
                continue
            mid_str = str(fid)
            lobj = League.objects.filter(api_league_id=lid).first()
            htobj = Team.objects.filter(api_team_id=htid).first()
            atobj = Team.objects.filter(api_team_id=atid).first()
            
            if not lobj: logger.warning(f"League {lid} not found for fixture {mid_str}.")
            if not htobj: logger.warning(f"Home team {htid} not found for fixture {mid_str}.")
            if not atobj: logger.warning(f"Away team {atid} not found for fixture {mid_str}.")
            
            defs = {
                'league': lobj, 'home_team': htobj, 'away_team': atobj,
                'match_date': parse_datetime_from_api(fi.get("date"), "fix.date"),
                'status_short': fi.get("status", {}).get("short", "N/A"), 
                'status_long': fi.get("status", {}).get("long", "N/A"),
                'venue_name': fi.get("venue", {}).get("name"), 'referee': fi.get("referee"), 
                'round': li.get("round"), 'home_team_score': gi.get("home"),
                'away_team_score': gi.get("away"),
                'halftime_home_score': si.get("halftime", {}).get("home"), 
                'halftime_away_score': si.get("halftime", {}).get("away"),
                'extratime_home_score': si.get("extratime", {}).get("home"), 
                'extratime_away_score': si.get("extratime", {}).get("away"),
                'penalty_home_score': si.get("penalty", {}).get("home"), 
                'penalty_away_score': si.get("penalty", {}).get("away"),
                'api_fixture_timestamp': parse_datetime_from_api(fi.get("timestamp"), "fix.ts"),
                'is_result_confirmed': fi.get("status", {}).get("short") in ["FT", "AET", "PEN", "AWDD", "ABD", "WO"]
            }
            _, created = FootballFixture.objects.update_or_create(match_api_id=mid_str, defaults=defs)
            if created: 
                created_c += 1
            else: 
                updated_c +=1
        except Exception as e: 
            logger.error(f"Error processing fixture: {item}. E: {e}", exc_info=True)
    logger.info(f"Fixtures: {created_c} created, {updated_c} updated from {len(all_fixture_data)}.")

@transaction.atomic
def fetch_and_update_odds_for_fixture(fixture_api_id, bookmaker_api_id_filter=None):
    logger.info(f"Fn fetch_odds: FixID:{fixture_api_id}, BookieFilter:{bookmaker_api_id_filter}")
    try: 
        fixture_obj = FootballFixture.objects.get(match_api_id=str(fixture_api_id))
    except FootballFixture.DoesNotExist: 
        logger.error(f"Fixture {fixture_api_id} not in DB. No odds fetch.")
        return
        
    params = {'fixture': str(fixture_api_id)}
    if bookmaker_api_id_filter: 
        params['bookmaker'] = str(bookmaker_api_id_filter)
    
    is_paginated_call = False 
    data = _make_api_request("odds", params=params, is_paginated_endpoint=is_paginated_call, page=None)

    if not data or not data.get("response"): 
        logger.warning(f"No odds data or API error for fix {fixture_api_id}. Params:{params}")
        return
        
    api_response = data.get("response", [])
    if not isinstance(api_response, list): 
        logger.error(f"Odds API 'response' not list. Params:{params}")
        return
        
    if not api_response: 
        logger.info(f"Empty 'response' for odds for fix {fixture_api_id}.")
        return
    
    mk_c=0; mk_u=0; out_c=0; out_u=0
    for odds_fix_item in api_response:
        if not isinstance(odds_fix_item, dict): 
            logger.warning(f"Skip odds item, not dict: {odds_fix_item}")
            continue
            
        upd_time = parse_datetime_from_api(odds_fix_item.get("update"), "odds.update")
        for bookie_data in odds_fix_item.get("bookmakers", []):
            if not isinstance(bookie_data, dict): 
                logger.warning(f"Skip bookie, not dict: {bookie_data}")
                continue
                
            bid = bookie_data.get("id"); bname = bookie_data.get("name", "N/A")
            if not bid: 
                logger.warning(f"Skip bookie, no ID: {bookie_data}")
                continue
                
            try:
                bobj, _ = Bookmaker.objects.update_or_create(api_bookmaker_id=bid, defaults={'name': bname})
                for market_api in bookie_data.get("bets", []):
                    if not isinstance(market_api, dict): 
                        logger.warning(f"Skip market, not dict: {market_api}")
                        continue
                        
                    mname = market_api.get("name", "N/A"); mid = market_api.get("id")
                    mcatobj, _ = MarketCategory.objects.get_or_create(name=mname, defaults={'description': f"API ID:{mid if mid else 'N/A'}"})
                    mparam = None # TODO: Implement robust parsing logic for parameterized markets
                    
                    market_obj, mc = Market.objects.update_or_create( # Renamed from mobj to market_obj for clarity
                        fixture=fixture_obj, bookmaker=bobj, category=mcatobj, market_parameter=mparam,
                        defaults={'is_active': True, 'last_updated_odds_api': upd_time}
                    )
                    if mc: mk_c += 1
                    else: mk_u += 1
                    
                    outcomes = market_api.get("values", [])
                    if not isinstance(outcomes, list): 
                        logger.warning(f"Outcomes not list for market '{mname}'")
                        continue
                        
                    for out_data in outcomes:
                        if not isinstance(out_data, dict): 
                            logger.warning(f"Skip outcome, not dict: {out_data}")
                            continue
                            
                        oname = out_data.get("value"); oodds = out_data.get("odd")
                        if oname is None or oodds is None: 
                            logger.warning(f"Skip outcome, no name/odds: {out_data}")
                            continue
                            
                        try: 
                            dec_odds = float(str(oodds).strip())
                        except Exception: 
                            logger.warning(f"Invalid odds format '{oodds}' for outcome '{oname}'. Skip.")
                            continue
                            
                        _, oc = MarketOutcome.objects.update_or_create(
                            market=market_obj, # Corrected from mobj
                            outcome_name=oname, 
                            defaults={'odds': dec_odds, 'is_suspended': False}
                        )
                        if oc: out_c +=1
                        else: out_u +=1
            except Exception as e: 
                logger.error(f"Error processing odds for bookie {bid}, fix {fixture_api_id}: {e}", exc_info=True)
    logger.info(f"Odds fix {fixture_api_id}: {mk_c} markets_c, {mk_u} markets_u, {out_c} outcomes_c, {out_u} outcomes_u.")

def run_full_data_update_for_leagues(league_api_ids, current_season_year, fetch_odds=True):
    if not isinstance(league_api_ids, list) or not league_api_ids:
        logger.error("Orchestrator: league_api_ids must be a non-empty list.")
        return "Error: league_api_ids must be a list."
    logger.info(f"--- Orchestrator Starting: Leagues {league_api_ids}, Season {current_season_year}, FetchOdds: {fetch_odds} ---")
    
    fetch_and_update_leagues(league_ids=league_api_ids, season=current_season_year)
    time.sleep(API_CALL_DELAY_SECONDS * 2)
    
    leagues_to_process_ids_int = []
    for lid in league_api_ids:
        try: 
            leagues_to_process_ids_int.append(int(lid))
        except ValueError: 
            logger.warning(f"Invalid league ID format in list for DB query: {lid}")
    
    if not leagues_to_process_ids_int:
        logger.warning("Orchestrator: No valid integer league IDs to process after conversion.")
        return "No valid integer league IDs provided."

    leagues_in_db = League.objects.filter(api_league_id__in=leagues_to_process_ids_int)
    
    if not leagues_in_db.exists():
        logger.warning(f"Orchestrator: None of requested leagues {leagues_to_process_ids_int} found in DB after fetch attempt. Aborting.")
        return f"No valid leagues found in DB for IDs: {leagues_to_process_ids_int}."

    for league in leagues_in_db:
        logger.info(f"\nOrchestrator processing League: {league.name} (API ID: {league.api_league_id}) for season {current_season_year}")
        fetch_and_update_teams_for_league_season(league.api_league_id, current_season_year)
        time.sleep(API_CALL_DELAY_SECONDS)
        
        fetch_and_update_fixtures(league_api_id=league.api_league_id, season_year=current_season_year)
        time.sleep(API_CALL_DELAY_SECONDS * 2)

        if fetch_odds:
            pending_statuses = ['NS', 'TBD', 'PST'] 
            now_aware = django_timezone.now()
            
            fixtures_needing_odds = FootballFixture.objects.filter(
                league=league, status_short__in=pending_statuses, match_date__gte=now_aware
            ).order_by('match_date')[:20]

            logger.info(f"Orchestrator: Found {fixtures_needing_odds.count()} fixtures in league {league.name} for odds fetch.")
            for fixture in fixtures_needing_odds:
                logger.info(f"Orchestrator: Fetching odds for fixture: {fixture} (API ID: {fixture.match_api_id})")
                fetch_and_update_odds_for_fixture(fixture.match_api_id)
                time.sleep(API_CALL_DELAY_SECONDS)
    
    logger.info(f"--- Orchestrator Completed for Leagues: {league_api_ids}, Season: {current_season_year} ---")
    return f"Full data update for leagues {league_api_ids} completed."

