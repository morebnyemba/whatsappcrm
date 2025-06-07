# football_data_app/the_odds_api_client.py
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

THE_ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_TIMEOUT = 30 # seconds

class TheOddsAPIException(Exception):
    """Custom exception for The Odds API client errors."""
    def __init__(self, message, status_code=None, response_text=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

class TheOddsAPIClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'THE_ODDS_API_KEY', None)
        if not self.api_key:
            logger.critical("THE_ODDS_API_KEY is not configured in Django settings.")
            raise ValueError("THE_ODDS_API_KEY must be set in Django settings or passed to client.")

    def _request(self, method, endpoint, params=None, data=None):
        url = f"{THE_ODDS_API_BASE_URL}{endpoint}"
        if params is None:
            params = {}
        # Ensure API key is always present in the request parameters.
        params['apiKey'] = self.api_key

        try:
            logger.debug(f"Requesting The Odds API: {method} {url} with params {params}")
            response = requests.request(method, url, params=params, json=data, timeout=DEFAULT_TIMEOUT)
            
            requests_remaining = response.headers.get('x-requests-remaining')
            requests_used = response.headers.get('x-requests-used')
            if requests_remaining is not None:
                logger.info(f"The Odds API: Requests remaining: {requests_remaining}, Used: {requests_used}")

            response.raise_for_status() # Raises HTTPError for 4xx/5xx responses
            return response.json()

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            response_text = e.response.text if e.response else "No response body"
            logger.error(f"The Odds API HTTPError for {method} {url}: {e}. Status: {status_code}. Response: {response_text[:500]}")
            raise TheOddsAPIException(f"HTTP error: {e}", status_code=status_code, response_text=response_text) from e
        except requests.exceptions.Timeout as e:
            logger.error(f"The Odds API Timeout for {method} {url}: {e}")
            raise TheOddsAPIException(f"Request timed out: {e}", response_text=str(e)) from e
        except requests.exceptions.RequestException as e:
            logger.error(f"The Odds API RequestException for {method} {url}: {e}")
            raise TheOddsAPIException(f"Generic request error: {e}", response_text=str(e)) from e
        except ValueError as e: # Handles JSON decoding errors
            response_text_for_log = response.text[:500] if 'response' in locals() and hasattr(response, 'text') else "Response not available or not text."
            logger.error(f"The Odds API JSONDecodeError for {method} {url}: {e}. Response text: {response_text_for_log}")
            raise TheOddsAPIException(f"Failed to decode JSON response: {e}", response_text=response_text_for_log if 'response' in locals() else None) from e

    def get_sports(self, all_sports=False):
        """Fetches available sports."""
        params = {}
        if all_sports:
            params['all'] = 'true' 
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key):
        """Fetches event IDs and basic details for a sport, without odds."""
        endpoint = f"/sports/{sport_key}/events"
        return self._request("GET", endpoint)

    def get_odds(self, sport_key, regions, markets="h2h", event_ids=None, commence_time_from=None, commence_time_to=None):
        """
        Fetches odds. If specific event_ids are provided, it uses those. 
        Otherwise, it can use a date range, but this is now handled more carefully in the calling task.
        """
        endpoint = f"/sports/{sport_key}/odds"
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        elif commence_time_from and commence_time_to:
            params['commenceTimeFrom'] = commence_time_from
            params['commenceTimeTo'] = commence_time_to
        
        return self._request("GET", endpoint, params=params)

    def get_scores(self, sport_key, event_ids):
        """Fetches scores for specific events."""
        if not event_ids:
            logger.warning(f"get_scores called for {sport_key} without event_ids.")
            return []
            
        endpoint = f"/sports/{sport_key}/scores"
        params = { "eventIds": ",".join(event_ids) }
        return self._request("GET", endpoint, params=params)

