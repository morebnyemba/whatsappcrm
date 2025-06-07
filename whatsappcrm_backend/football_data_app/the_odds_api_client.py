# football_data_app/the_odds_api_client.py
import requests
import logging
from django.conf import settings # For THE_ODDS_API_KEY

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
        # Ensure essential_params (like apiKey) are part of the main params dict
        # and not accidentally overwritten by caller's params.
        # The apiKey is now added directly in each method that calls _request.
        
        try:
            logger.debug(f"Requesting The Odds API: {method} {url} with params {params}")
            response = requests.request(method, url, params=params, json=data, timeout=DEFAULT_TIMEOUT)
            
            requests_remaining = response.headers.get('x-requests-remaining')
            requests_used = response.headers.get('x-requests-used')
            if requests_remaining is not None:
                logger.info(f"The Odds API: Requests remaining: {requests_remaining}, Used: {requests_used}")

            if response.status_code == 401:
                logger.error(f"The Odds API Unauthorized (401). Check API key. Endpoint: {endpoint}")
                raise TheOddsAPIException("Unauthorized. Check API Key.", status_code=401, response_text=response.text)
            if response.status_code == 429:
                 retry_after = response.headers.get("Retry-After")
                 logger.warning(f"The Odds API Rate Limit (429) or too many requests. Retry-After: {retry_after}. Endpoint: {endpoint}")
                 # The message for TheOddsAPIException should be informative for retry logic in tasks
                 raise TheOddsAPIException(f"Rate limit exceeded. Retry after {retry_after} seconds. {response.text}", status_code=429, response_text=response.text)
            
            response.raise_for_status() # Raises HTTPError for other 4xx/5xx
            return response.json()

        except requests.exceptions.Timeout as e:
            logger.error(f"The Odds API Timeout for {method} {url}: {e}")
            raise TheOddsAPIException(f"Request timed out: {e}", response_text=str(e))
        except requests.exceptions.ConnectionError as e:
            logger.error(f"The Odds API ConnectionError for {method} {url}: {e}")
            raise TheOddsAPIException(f"Connection error: {e}", response_text=str(e))
        except requests.exceptions.HTTPError as e:
            response_details = e.response.text[:500] if e.response else "No response body"
            logger.error(f"The Odds API HTTPError for {method} {url}: {e}. Status: {e.response.status_code if e.response else 'N/A'}. Response: {response_details}")
            raise TheOddsAPIException(f"HTTP error: {e}", status_code=e.response.status_code if e.response else None, response_text=e.response.text if e.response else None)
        except requests.exceptions.RequestException as e:
            logger.error(f"The Odds API RequestException for {method} {url}: {e}")
            raise TheOddsAPIException(f"Generic request error: {e}", response_text=str(e))
        except ValueError as e: # Handles JSON decoding errors
            # Ensure response object exists before trying to access its text attribute
            response_text_for_log = response.text[:500] if 'response' in locals() and hasattr(response, 'text') else "Response not available or not text."
            logger.error(f"The Odds API JSONDecodeError for {method} {url}: {e}. Response text: {response_text_for_log}")
            raise TheOddsAPIException(f"Failed to decode JSON response: {e}", response_text=response_text_for_log if 'response' in locals() and hasattr(response, 'text') else None)


    def get_sports(self, all_sports=False):
        """Fetches available sports."""
        params = {'apiKey': self.api_key}
        if all_sports:
            params['all'] = 'true' 
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key, event_ids=None, commence_date_from=None, commence_date_to=None):
        """Fetches event IDs and basic details for a sport, without odds."""
        endpoint = f"/sports/{sport_key}/events"
        params = {'apiKey': self.api_key}
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        if commence_date_from:
            params['dateFrom'] = commence_date_from
        if commence_date_to:
            params['dateTo'] = commence_date_to
        return self._request("GET", endpoint, params=params)

    def get_odds(self, sport_key, regions, markets="h2h", odds_format="decimal", date_format="iso", 
                 event_ids=None, bookmakers=None, commence_time_from=None, commence_time_to=None):
        """Fetches odds, including event details, for a given sport and criteria."""
        endpoint = f"/sports/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if event_ids: 
            params['eventIds'] = ",".join(event_ids)
        else: # If no specific event_ids, time window might be used for non-outright sports
            if not sport_key.endswith("_winner"): # Only apply date filters if not an outright winner market
                if commence_time_from:
                    params['commenceTimeFrom'] = commence_time_from
                if commence_time_to:
                    params['commenceTimeTo'] = commence_time_to
            else:
                logger.info(f"Omitting date params for outright sport_key during odds fetch: {sport_key}")
        
        if bookmakers:
            params['bookmakers'] = ",".join(bookmakers)
        
        return self._request("GET", endpoint, params=params)

    def get_scores(self, sport_key, event_ids=None, days_from=None, date_format="iso"):
        """Fetches scores for events."""
        endpoint = f"/sports/{sport_key}/scores"
        params = {"apiKey": self.api_key, "dateFormat": date_format}
        if event_ids:
            params['eventIds'] = ",".join(event_ids)
        if days_from is not None:
            params['daysFrom'] = days_from
        return self._request("GET", endpoint, params=params)
