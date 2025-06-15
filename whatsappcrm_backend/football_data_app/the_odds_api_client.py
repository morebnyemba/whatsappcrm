import os
import requests
import logging
import time
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TheOddsAPIException(Exception):
    """Custom exception for API errors with detailed context."""
    def __init__(self, message: str, status_code: Optional[int] = None, 
                 response_text: Optional[str] = None, url: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.response_text = response_text
        self.url = url
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        msg = f"The Odds API Error: {self.message}"
        if self.status_code:
            msg += f" (Status: {self.status_code})"
        if self.url:
            msg += f" for URL: {self.url}"
        if self.response_text:
            msg += f" - Response: {self.response_text[:200]}"
        return msg

class TheOddsAPIClient:
    """Production-ready client for The Odds API with complete error handling."""

    BASE_URL = "https://api.the-odds-api.com/v4"
    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 5  # seconds
    QUOTA_EXHAUSTED_DELAY = 3600  # 1 hour

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('THE_ODDS_API_KEY')
        if not self.api_key:
            logger.critical("API key not configured")
            raise ValueError("THE_ODDS_API_KEY must be set")
        
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'SportsDataApp/1.0'
        })
        self._last_request_time = None
        self._rate_limit_remaining = 100  # Conservative default

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        attempt: int = 0
    ) -> Union[dict, list]:
        """Core request method with complete error handling."""
        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}
        params['apiKey'] = self.api_key

        try:
            self._enforce_rate_limit()
            
            logger.debug(f"Request: {method} {url} with params {self._sanitize_params(params)}")
            
            response = self.session.request(
                method,
                url,
                params=params,
                timeout=self.DEFAULT_TIMEOUT
            )
            
            self._update_rate_limit_metrics(response)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            return self._handle_http_error(e, method, url, params, attempt)
        except requests.exceptions.RequestException as e:
            return self._handle_connection_error(e, method, url, params, attempt)

    def _enforce_rate_limit(self):
        """Ensure we don't exceed rate limits."""
        if self._last_request_time and self._rate_limit_remaining < 5:
            elapsed = (datetime.now() - self._last_request_time).total_seconds()
            if elapsed < 1:
                time.sleep(1 - elapsed)
        self._last_request_time = datetime.now()

    def _update_rate_limit_metrics(self, response: requests.Response):
        """Track rate limit usage from headers."""
        remaining = response.headers.get('x-requests-remaining')
        if remaining:
            self._rate_limit_remaining = int(remaining)
            used = response.headers.get('x-requests-used', '?')
            logger.info(f"Rate limits - Remaining: {remaining}, Used: {used}")

    def _handle_http_error(self, e, method, url, params, attempt):
        """Handle HTTP errors with proper retry logic."""
        status_code = getattr(e.response, 'status_code', None)
        response_text = getattr(e.response, 'text', '')
        
        # Special case: Quota exhausted
        if status_code == 401 and 'OUT_OF_USAGE_CREDITS' in response_text:
            if attempt < self.MAX_RETRIES:
                logger.error("API quota exhausted - waiting before retry")
                time.sleep(self.QUOTA_EXHAUSTED_DELAY)
                return self._make_request(method, url, params, attempt + 1)
            raise TheOddsAPIException(
                "API quota exhausted after retries",
                status_code,
                response_text,
                url
            )
            
        # Not Found - don't retry
        if status_code == 404:
            raise TheOddsAPIException(
                "Resource not found",
                status_code,
                response_text,
                url
            )
            
        # Rate limited - respect Retry-After header
        if status_code == 429:
            retry_after = int(e.response.headers.get('Retry-After', self.BASE_RETRY_DELAY))
            if attempt < self.MAX_RETRIES:
                logger.warning(f"Rate limited - retrying after {retry_after}s")
                time.sleep(retry_after)
                return self._make_request(method, url, params, attempt + 1)
            raise TheOddsAPIException(
                "Rate limited after max retries",
                status_code,
                response_text,
                url
            )
            
        # Server errors - retry with backoff
        if status_code and 500 <= status_code < 600:
            if attempt < self.MAX_RETRIES:
                delay = self.BASE_RETRY_DELAY * (attempt + 1)
                logger.warning(f"Server error {status_code} - retrying in {delay}s")
                time.sleep(delay)
                return self._make_request(method, url, params, attempt + 1)
                
        # All other HTTP errors
        raise TheOddsAPIException(
            f"HTTP request failed: {str(e)}",
            status_code,
            response_text,
            url
        )

    def _handle_connection_error(self, e, method, url, params, attempt):
        """Handle network issues with retries."""
        if attempt < self.MAX_RETRIES:
            delay = self.BASE_RETRY_DELAY * (attempt + 1)
            logger.warning(f"Connection error - retrying in {delay}s: {str(e)}")
            time.sleep(delay)
            return self._make_request(method, url, params, attempt + 1)
        raise TheOddsAPIException(
            f"Connection failed after retries: {str(e)}",
            None,
            None,
            url
        )

    def _sanitize_params(self, params: dict) -> dict:
        """Remove sensitive info from logged params."""
        return {k: v for k, v in params.items() if k != 'apiKey'}

    # Public API Methods

    def get_sports(self, all_sports: bool = False) -> List[dict]:
        """Get all available sports."""
        params = {'all': 'true'} if all_sports else {}
        return self._make_request("GET", "/sports", params)

    def get_odds_batch(
        self,
        sport_key: str,
        event_ids: List[str],
        regions: str = "eu,uk,us",
        markets: str = "h2h,totals",
        bookmakers: Optional[str] = None
    ) -> List[dict]:
        """Batch fetch odds for multiple events."""
        if not event_ids:
            return []
            
        params = {
            "regions": regions,
            "markets": markets,
            "eventIds": ",".join(event_ids),
            "oddsFormat": "decimal",
            "dateFormat": "iso"
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
            
        return self._make_request("GET", f"/sports/{sport_key}/odds", params) or []

    def get_event_odds(
        self,
        event_id: str,
        regions: str = "eu,uk,us",
        markets: str = "h2h,totals",
        bookmakers: Optional[str] = None
    ) -> Optional[dict]:
        """Get odds for specific event."""
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
            "dateFormat": "iso"
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
            
        try:
            return self._make_request("GET", f"/events/{event_id}/odds", params)
        except TheOddsAPIException as e:
            if e.status_code == 404:
                logger.warning(f"Event {event_id} not found")
                return None
            raise

    def get_scores(
        self,
        sport_key: str,
        days_ago: int = 1,
        event_ids: Optional[List[str]] = None
    ) -> List[dict]:
        """Get completed event scores."""
        date_from = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        params = {"date": date_from}
        if event_ids:
            params["eventIds"] = ",".join(event_ids)
        return self._make_request("GET", f"/sports/{sport_key}/scores", params) or []