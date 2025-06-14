# football_data_app/the_odds_api_client.py
import os
import requests
import logging
from typing import List, Optional

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
        self.api_key = api_key or os.getenv('THE_ODDS_API_KEY')
        if not self.api_key:
            logger.critical("THE_ODDS_API_KEY environment variable not set. This will prevent API calls.")
            raise ValueError("THE_ODDS_API_KEY must be set.")
        logger.debug("TheOddsAPIClient initialized.")

    def _request(self, method: str, endpoint: str, params: Optional[dict] = None) -> dict:
        """Internal method to handle all live API requests."""
        url = f"{THE_ODDS_API_BASE_URL}{endpoint}"
        
        request_params = params.copy() if params else {}
        request_params['apiKey'] = self.api_key

        try:
            safe_params = {k: v for k, v in request_params.items() if k != 'apiKey'}
            logger.debug(f"API Request: Method={method}, URL={url}, Params={safe_params}")
            
            response = requests.request(method, url, params=request_params, timeout=DEFAULT_TIMEOUT)
            
            remaining = response.headers.get('x-requests-remaining')
            used = response.headers.get('x-requests-used')
            if remaining:
                logger.info(f"The Odds API Rate Limit: Remaining: {remaining}, Used: {used}")

            response.raise_for_status()
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
                f"Response: '{response_text[:400]}...'"
            )
            logger.warning(log_message)
            raise TheOddsAPIException(
                f"HTTP error: {e}", status_code, response_text, response_json
            ) from e
        except requests.exceptions.RequestException as e:
            logger.error(f"The Odds API RequestException for {method} {url}: {e}")
            raise TheOddsAPIException(f"Request failed: {e}") from e

    def get_sports(self, all_sports: bool = False) -> List[dict]:
        params = {'all': 'true'} if all_sports else {}
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key: str) -> List[dict]:
        return self._request("GET", f"/sports/{sport_key}/events")

    def get_odds(self, sport_key: str, regions: str, markets: str, event_ids: List[str], bookmakers: Optional[str] = None) -> List[dict]:
        if not event_ids: return []
        params = {
            "regions": regions, "markets": markets,
            "oddsFormat": "decimal", "dateFormat": "iso",
            "eventIds": ",".join(event_ids),
        }
        if bookmakers:
            params['bookmakers'] = bookmakers
        return self._request("GET", f"/sports/{sport_key}/odds", params=params)

    def get_event_odds(self, event_id: str, regions: str, markets: str, bookmakers: Optional[str] = None) -> dict:
        params = {
            "regions": regions, "markets": markets,
            "oddsFormat": "decimal", "dateFormat": "iso",
        }
        if bookmakers:
            params['bookmakers'] = bookmakers
        return self._request("GET", f"/events/{event_id}/odds", params=params)

    def get_scores(self, sport_key: str, event_ids: Optional[List[str]] = None) -> List[dict]:
        params = {}
        if event_ids:
            params['eventIds'] = ','.join(event_ids)
        return self._request("GET", f"/sports/{sport_key}/scores", params=params)