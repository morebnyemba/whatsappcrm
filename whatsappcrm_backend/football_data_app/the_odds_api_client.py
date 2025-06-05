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
            # This will be caught by tasks and logged, preventing system crash if key is missing.
            logger.critical("THE_ODDS_API_KEY is not configured in Django settings.")
            raise ValueError("THE_ODDS_API_KEY must be set in Django settings or passed to client.")

    def _request(self, method, endpoint, params=None, data=None):
        url = f"{THE_ODDS_API_BASE_URL}{endpoint}"
        if params is None:
            params = {}
        # Ensure API key is present for every request attempt.
        if not self.api_key: # Should have been caught in __init__, but as a safeguard.
             logger.error("API key missing during request preparation.")
             raise TheOddsAPIException("API key not available for request.", status_code=None) # Or a specific internal error code
        
        params['apiKey'] = self.api_key

        try:
            logger.debug(f"Requesting The Odds API: {method} {url} with params {params}")
            response = requests.request(method, url, params=params, json=data, timeout=DEFAULT_TIMEOUT)
            
            requests_remaining = response.headers.get('x-requests-remaining')
            requests_used = response.headers.get('x-requests-used')
            if requests_remaining is not None: # Check for None, as header might not always be present
                logger.info(f"The Odds API: Requests remaining: {requests_remaining}, Used: {requests_used}")

            if response.status_code == 401:
                logger.error(f"The Odds API Unauthorized (401). Check API key. Endpoint: {endpoint}")
                raise TheOddsAPIException("Unauthorized. Check API Key.", status_code=401, response_text=response.text)
            if response.status_code == 429:
                 retry_after = response.headers.get("Retry-After")
                 logger.warning(f"The Odds API Rate Limit (429) or too many requests. Retry-After: {retry_after}. Endpoint: {endpoint}")
                 raise TheOddsAPIException(f"Rate limit exceeded. Retry after {retry_after} seconds.", status_code=429, response_text=response.text)
            
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout as e:
            logger.error(f"The Odds API Timeout for {method} {url}: {e}")
            raise TheOddsAPIException(f"Request timed out: {e}", response_text=str(e))
        except requests.exceptions.ConnectionError as e:
            logger.error(f"The Odds API ConnectionError for {method} {url}: {e}")
            raise TheOddsAPIException(f"Connection error: {e}", response_text=str(e))
        except requests.exceptions.HTTPError as e:
            # Log more details from the response if available
            response_details = e.response.text[:500] if e.response else "No response body"
            logger.error(f"The Odds API HTTPError for {method} {url}: {e}. Status: {e.response.status_code if e.response else 'N/A'}. Response: {response_details}")
            raise TheOddsAPIException(f"HTTP error: {e}", status_code=e.response.status_code if e.response else None, response_text=e.response.text if e.response else None)
        except requests.exceptions.RequestException as e: # Catch-all for other requests-related errors
            logger.error(f"The Odds API RequestException for {method} {url}: {e}")
            raise TheOddsAPIException(f"Generic request error: {e}", response_text=str(e))
        except ValueError as e: # Handles JSON decoding errors
            logger.error(f"The Odds API JSONDecodeError for {method} {url}: {e}. Response text: {response.text[:500] if 'response' in locals() else 'Response not available'}")
            raise TheOddsAPIException(f"Failed to decode JSON response: {e}", response_text=response.text if 'response' in locals() else None)


    def get_sports(self, all_sports=False):
        """Fetches available sports."""
        params = {}
        if all_sports:
            params['all'] = 'true' 
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key, event_ids=None, commence_date_from=None, commence_date_to=None):
        """
        Fetches event IDs and basic details for a sport, without odds.
        Useful for discovering events that exist in The Odds API system.
        This endpoint typically does not count significantly against usage quota.
        """
        endpoint = f"/sports/{sport_key}/events"
        params = {}
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        if commence_date_from: # ISO8601 format e.g. 2023-06-01T00:00:00Z
            params['dateFrom'] = commence_date_from # Check API docs for exact param name if different
        if commence_date_to:
            params['dateTo'] = commence_date_to # Check API docs for exact param name if different
        return self._request("GET", endpoint, params=params)

    def get_odds(self, sport_key, regions, markets="h2h", odds_format="decimal", date_format="iso", event_ids=None, bookmakers=None, commence_time_from=None, commence_time_to=None):
        """Fetches odds, including event details, for a given sport and criteria."""
        endpoint = f"/sports/{sport_key}/odds"
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        if bookmakers:
            params['bookmakers'] = ",".join(bookmakers)
        if commence_time_to: # API uses 'commenceTimeTo'
            params['commenceTimeTo'] = commence_time_to 
        if commence_time_from:
             params['commenceTimeFrom'] = commence_time_from
        return self._request("GET", endpoint, params=params)

    def get_scores(self, sport_key, event_ids=None, days_from=None, date_format="iso"):
        """Fetches scores for events."""
        endpoint = f"/sports/{sport_key}/scores"
        params = {"dateFormat": date_format}
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        if days_from is not None: # Ensure it's not None before adding
            params['daysFrom'] = days_from
        return self._request("GET", endpoint, params=params)