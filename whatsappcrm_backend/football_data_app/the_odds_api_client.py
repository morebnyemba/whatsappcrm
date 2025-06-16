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
        self.api_key = api_key or os.getenv('THE_ODDS_API_KEY')
        if not self.api_key:
            logger.critical("THE_ODDS_API_KEY environment variable not set. This will prevent API calls.")
            raise ValueError("THE_ODDS_API_KEY must be set.")
        logger.debug("TheOddsAPIClient initialized.")

    def _request(self, method: str, endpoint: str, params: Optional[dict] = None) -> Union[Dict, List]:
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
        """Get list of available sports."""
        params = {'all': 'true'} if all_sports else {}
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key: str, days_from_now: Optional[int] = None) -> List[dict]:
        """Get events for a specific sport, optionally filtered by date range."""
        params = {}
        if days_from_now is not None:
            date_from = datetime.utcnow()
            date_to = date_from + timedelta(days=days_from_now)
            params['commenceTimeFrom'] = date_from.isoformat() + 'Z'
            params['commenceTimeTo'] = date_to.isoformat() + 'Z'
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
        event_id: str,
        regions: str = 'uk,eu,us,au',
        markets: str = 'h2h,totals',
        bookmakers: Optional[str] = None,
        odds_format: str = 'decimal',
        date_format: str = 'iso'
    ) -> dict:
        """Get odds for a specific event."""
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if bookmakers:
            params['bookmakers'] = bookmakers
        return self._request("GET", f"/events/{event_id}/odds", params=params)

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