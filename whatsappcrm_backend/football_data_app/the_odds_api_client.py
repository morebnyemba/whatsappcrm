# football_data_app/the_odds_api_client.py
import os
import requests
import logging
from typing import List, Optional, Dict, Union
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

THE_ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_TIMEOUT = 30

class TheOddsAPIException(Exception):
    """Custom exception for The Odds API client errors."""
    def __init__(self, message, status_code=None, response_text=None, response_json=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text
        self.response_json = response_json

class TheOddsAPIClient:
    """A robust client for making live requests to The Odds API."""
    def __init__(self, api_key: Optional[str] = None):
        _api_key_to_use = api_key

        if not _api_key_to_use:
            try:
                # Local import to avoid issues if Django isn't fully configured when module is loaded
                from football_data_app.models import Configuration
                config = Configuration.objects.filter(provider_name="The Odds API").first()
                if config and config.api_key:
                    _api_key_to_use = config.api_key
                    logger.info("API Key loaded from database Configuration for 'The Odds API'.")
                else:
                    logger.info(
                        "No 'The Odds API' configuration found in database, or API key is missing in the config. "
                        "Will try environment variable."
                    )
            except ImportError:
                logger.warning(
                    "Django models could not be imported (Django not configured or models not accessible). "
                    "Cannot fetch API key from database. Will try environment variable."
                )
            except Exception as e: # Catch other potential DB errors (e.g., OperationalError if DB not ready)
                logger.error(f"Error fetching API key from database: {e}. Will try environment variable.")
        
        if not _api_key_to_use:
            _api_key_to_use = os.getenv('THE_ODDS_API_KEY')
            if _api_key_to_use:
                logger.info("API Key loaded from THE_ODDS_API_KEY environment variable (as fallback or if DB lookup failed/not configured).")

        if not _api_key_to_use:
            logger.critical("API Key for The Odds API is not configured. Please provide it to the client, "
                            "set it in the database Configuration, or set the THE_ODDS_API_KEY environment variable.")
            raise ValueError("API Key for The Odds API must be configured.")
        
        self.api_key = _api_key_to_use
        logger.debug(f"TheOddsAPIClient initialized with API key ending in '...{self.api_key[-4:] if len(self.api_key) >=4 else self.api_key}'.")

    def _request(self, method: str, endpoint: str, params: Optional[dict] = None) -> Union[Dict, List]:
        """Internal method to handle all live API requests."""
        url = f"{THE_ODDS_API_BASE_URL}{endpoint}"
        
        request_params = params.copy() if params else {}
        request_params['apiKey'] = self.api_key
        full_url_with_key = f"{url}?{requests.compat.urlencode(request_params)}" # For potential full URL logging (key included)

        try:
            # Log the request URL without the API key for security in general logs
            # Create a temporary dict for logging params without the API key
            logged_params = {k: v for k, v in request_params.items() if k != 'apiKey'}
            log_url_display = f"{url}?{requests.compat.urlencode(logged_params)}" if logged_params else url
            logger.info(f"TheOddsAPI Request: Method={method}, URL='{log_url_display}'")
            # For more detailed debugging, one might log the full_url_with_key, but be cautious.
            # logger.debug(f"TheOddsAPI Full Request URL (with key, for debugging only): {full_url_with_key}")
            
            response = requests.request(method, url, params=request_params, timeout=DEFAULT_TIMEOUT)
            
            remaining = response.headers.get('x-requests-remaining')
            used = response.headers.get('x-requests-used')
            if remaining is not None and used is not None: # Check if headers are present
                logger.info(f"The Odds API Rate Limit: Remaining: {remaining}, Used: {used}")

            response.raise_for_status()
            logger.debug(f"TheOddsAPI Response: Status={response.status_code}, URL='{response.url}', Content (snippet)='{response.text[:200]}...'")
            return response.json()

        except requests.exceptions.HTTPError as e:
            status_code = getattr(e.response, 'status_code', None)
            response_text = getattr(e.response, 'text', "No response body")
            try:
                response_json = e.response.json() if e.response and e.response.text else None
            except ValueError:
                response_json = None
            
            log_message = (
                f"The Odds API HTTPError for {method} {url}: {e}. Status: {status_code}. "
                f"Response: '{response_text[:400]}{'...' if len(response_text) > 400 else ''}'"
            )
            logger.warning(log_message)
            raise TheOddsAPIException(
                f"HTTP error for {method} {url}: {e}", status_code, response_text, response_json
            ) from e
        except requests.exceptions.RequestException as e:
            logger.error(f"The Odds API RequestException for {method} {url}: {e}")
            raise TheOddsAPIException(f"Request failed: {e}") from e

    def get_sports(self, all_sports: bool = False) -> List[dict]:
        """Get list of available sports."""
        params = {'all': 'true'} if all_sports else {}
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key: str, days_from_now: Optional[int] = None) -> List[dict]:
        """Get events for a specific sport, optionally filtered by date range."""
        params = {}
        if days_from_now is not None:
            date_from = datetime.utcnow()
            date_to = date_from + timedelta(days=days_from_now)
            # Format to YYYY-MM-DDTHH:MM:SSZ, excluding microseconds
            params['commenceTimeFrom'] = date_from.strftime('%Y-%m-%dT%H:%M:%SZ')
            params['commenceTimeTo'] = date_to.strftime('%Y-%m-%dT%H:%M:%SZ')
            logger.debug(f"Calculated commenceTimeFrom: {params['commenceTimeFrom']}, commenceTimeTo: {params['commenceTimeTo']} for get_events")
        return self._request("GET", f"/sports/{sport_key}/events", params=params)

    def get_odds(
        self,
        sport_key: str,
        regions: str = 'uk,eu,us,au',
        markets: str = 'h2h,totals',
        event_ids: Optional[List[str]] = None,
        bookmakers: Optional[str] = None,
        odds_format: str = 'decimal',
        date_format: str = 'iso',
        commence_time_from: Optional[str] = None,
        commence_time_to: Optional[str] = None
    ) -> List[dict]:
        """Get odds for specific events."""
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        if bookmakers:
            params['bookmakers'] = bookmakers
        if commence_time_from:
            params['commenceTimeFrom'] = commence_time_from
        if commence_time_to:
            params['commenceTimeTo'] = commence_time_to
            
        return self._request("GET", f"/sports/{sport_key}/odds", params=params)

    def get_event_odds(
        self,
        sport_key: str,
        event_id: str,
        regions: str = 'uk,eu,us,au',
        markets: str = 'h2h,totals', # Can be 'all' for this endpoint
        bookmakers: Optional[str] = None,
        odds_format: str = 'decimal',
        date_format: str = 'iso'
    ) -> Optional[dict]:
        """
        Get odds for a specific event using its sport_key and event_id.
        This method uses the dedicated single-event odds endpoint.
        """
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if bookmakers:
            params['bookmakers'] = bookmakers

        # Use the dedicated /sports/{sport_key}/events/{event_id}/odds endpoint
        endpoint = f"/sports/{sport_key}/events/{event_id}/odds"
        
        try:
            # This endpoint returns a single event object, not a list.
            result = self._request("GET", endpoint, params=params)
            
            if isinstance(result, dict) and result.get('id') == event_id:
                return result
            else:
                logger.warning(
                    f"API call to {endpoint} returned unexpected data structure or mismatched event ID. "
                    f"Expected ID: {event_id}, Received data (snippet): {str(result)[:200]}"
                )
                return None
        except TheOddsAPIException as e:
            # A 404 Not Found is a possible and non-critical error if an event has no odds.
            if e.status_code == 404:
                logger.info(f"No odds found for event {event_id} (404 Not Found). This can be normal.")
                return None
            # Re-raise other exceptions
            raise e

    def get_scores(
        self,
        sport_key: str,
        event_ids: Optional[List[str]] = None,
        days_from: Optional[int] = None
    ) -> List[dict]:
        """Get scores for completed events."""
        params = {}
        if event_ids:
            params['eventIds'] = ','.join(event_ids)
        if days_from:
            date_from = datetime.utcnow() - timedelta(days=days_from)
            params['dateFrom'] = date_from.isoformat() + 'Z'
        return self._request("GET", f"/sports/{sport_key}/scores", params=params)

    def get_historical_odds(
        self,
        sport_key: str,
        regions: str = 'uk,eu,us,au',
        markets: str = 'h2h,totals',
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        event_ids: Optional[List[str]] = None,
        bookmakers: Optional[str] = None,
        odds_format: str = 'decimal'
    ) -> List[dict]:
        """Get historical odds data."""
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
        }
        
        if date_from:
            params['dateFrom'] = date_from
        if date_to:
            params['dateTo'] = date_to
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        if bookmakers:
            params['bookmakers'] = bookmakers
            
        return self._request("GET", f"/sports/{sport_key}/odds-history", params=params)