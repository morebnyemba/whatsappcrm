# football_data_app/the_odds_api_client.py
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

THE_ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_TIMEOUT = 30 # seconds

class TheOddsAPIException(Exception):
    """Custom exception for The Odds API client errors."""
    def __init__(self, message, status_code=None, response_text=None, response_json=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text
        self.response_json = response_json

class TheOddsAPIClient:
    """A robust client for making live requests to The Odds API."""
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'THE_ODDS_API_KEY', None)
        if not self.api_key:
            logger.critical("THE_ODDS_API_KEY is not configured in Django settings. This will prevent API calls.")
            raise ValueError("THE_ODDS_API_KEY must be set in Django settings or passed to the client.")
        logger.debug("TheOddsAPIClient initialized.")

    def _request(self, method, endpoint, params=None):
        """
        Internal method to handle all live API requests, including robust error handling.
        """
        url = f"{THE_ODDS_API_BASE_URL}{endpoint}"
        
        request_params = params.copy() if params else {}
        request_params['apiKey'] = self.api_key

        response = None # Initialize response to None for wider scope
        try:
            # Log the full URL and parameters (excluding API key for security in non-debug logs)
            safe_params = {k: v for k, v in request_params.items() if k != 'apiKey'}
            logger.debug(f"API Request: Method={method}, URL={url}, Params={safe_params}")
            
            response = requests.request(method, url, params=request_params, timeout=DEFAULT_TIMEOUT)
            
            requests_remaining = response.headers.get('x-requests-remaining')
            requests_used = response.headers.get('x-requests-used')
            if requests_remaining is not None:
                logger.info(f"The Odds API Rate Limit: Remaining: {requests_remaining}, Used: {requests_used}")
            else:
                logger.debug("The Odds API rate limit headers not found in response.")

            response.raise_for_status()  # Raises HTTPError for 4xx/5xx responses
            logger.debug(f"API Response: Successful (Status: {response.status_code}) for {url}. Payload size: {len(response.content)} bytes.")
            return response.json()

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            response_text = e.response.text if e.response is not None else "No response body"
            response_json = None
            try:
                if e.response and e.response.text:
                    response_json = e.response.json()
            except ValueError:
                logger.debug(f"API HTTPError: Could not parse response body as JSON for {url}. Response text: {response_text[:200]} (truncated)")
                pass 

            log_message = (
                f"The Odds API HTTPError for {method} {url}: {e}. "
                f"Status: {status_code}. "
                f"Response Text: '{response_text[:500]} (truncated if long)'. "
                f"Response JSON: {response_json}"
            )
            if status_code in [401, 403]: # Unauthorized, Forbidden
                logger.critical(log_message)
            elif status_code == 429: # Too Many Requests
                logger.warning(log_message + " - Consider throttling or increasing rate limits.")
            elif status_code == 422: # Unprocessable Entity
                logger.warning(log_message + " - Often due to invalid or expired event IDs.")
            else:
                logger.error(log_message)

            raise TheOddsAPIException(
                f"HTTP error: {e}",
                status_code=status_code,
                response_text=response_text,
                response_json=response_json
            ) from e
        except requests.exceptions.Timeout as e:
            logger.error(f"The Odds API Timeout for {method} {url}: {e}. Consider increasing DEFAULT_TIMEOUT.")
            raise TheOddsAPIException(f"Request timed out: {e}", response_text=str(e)) from e
        except requests.exceptions.ConnectionError as e:
            logger.error(f"The Odds API ConnectionError for {method} {url}: {e}. Network issue or API server down?")
            raise TheOddsAPIException(f"Connection error: {e}", response_text=str(e)) from e
        except requests.exceptions.RequestException as e:
            logger.error(f"The Odds API Generic RequestException for {method} {url}: {e}. Unhandled request error.")
            raise TheOddsAPIException(f"Generic request error: {e}", response_text=str(e)) from e
        except ValueError as e:  # Handles JSON decoding errors from a *successful* 2xx response
            response_text_for_log = response.text[:500] if response and hasattr(response, 'text') else "Response not available."
            logger.error(f"The Odds API JSONDecodeError for {method} {url}: {e}. Received non-JSON response on success. Response text: {response_text_for_log}")
            raise TheOddsAPIException(f"Failed to decode JSON response: {e}", response_text=response_text_for_log) from e

    def get_sports(self, all_sports=False):
        """Fetches available sports."""
        logger.debug(f"Calling get_sports with all_sports={all_sports}")
        params = {'all': 'true'} if all_sports else {}
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key):
        """Fetches event IDs and basic details for a specific sport key."""
        logger.debug(f"Calling get_events for sport_key={sport_key}")
        endpoint = f"/sports/{sport_key}/events"
        return self._request("GET", endpoint)

    def get_odds(self, sport_key, regions, markets, event_ids):
        """Fetches odds for a specific list of event IDs."""
        if not event_ids:
            logger.warning(f"get_odds called for {sport_key} without event_ids. Skipping API call and returning empty list.")
            return []
            
        logger.debug(f"Calling get_odds for sport_key={sport_key}, regions={regions}, markets={markets}, event_ids_count={len(event_ids)}")
        endpoint = f"/sports/{sport_key}/odds"
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "eventIds": ",".join(event_ids),
        }
        return self._request("GET", endpoint, params=params)

    def get_scores(self, sport_key, event_ids):
        """Fetches scores for a specific list of events."""
        if not event_ids:
            logger.warning(f"get_scores called for {sport_key} without event_ids. Skipping API call and returning empty list.")
            return []
            
        logger.debug(f"Calling get_scores for sport_key={sport_key}, event_ids_count={len(event_ids)}")
        endpoint = f"/sports/{sport_key}/scores"
        params = {"eventIds": ",".join(event_ids)}
        return self._request("GET", endpoint, params=params)