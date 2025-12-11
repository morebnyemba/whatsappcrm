# football_data_app/apifootball_client.py
import os
import requests
import logging
from typing import List, Optional, Dict, Union
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

APIFOOTBALL_BASE_URL = "https://apifootball.com/api"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

class APIFootballException(Exception):
    """Custom exception for APIFootball client errors."""
    def __init__(self, message, status_code=None, response_text=None, response_json=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text
        self.response_json = response_json

class APIFootballClient:
    """A robust client for making requests to APIFootball.com."""
    
    def __init__(self, api_key: Optional[str] = None):
        _api_key_to_use = api_key

        if not _api_key_to_use:
            try:
                # Local import to avoid issues if Django isn't fully configured when module is loaded
                from football_data_app.models import Configuration
                config = Configuration.objects.filter(provider_name="APIFootball").first()
                if config and config.api_key:
                    _api_key_to_use = config.api_key
                    logger.info("API Key loaded from database Configuration for 'APIFootball'.")
                else:
                    logger.info(
                        "No 'APIFootball' configuration found in database, or API key is missing in the config. "
                        "Will try environment variable."
                    )
            except ImportError:
                logger.warning(
                    "Django models could not be imported (Django not configured or models not accessible). "
                    "Cannot fetch API key from database. Will try environment variable."
                )
            except Exception as e:
                logger.error(f"Error fetching API key from database: {e}. Will try environment variable.")
        
        if not _api_key_to_use:
            _api_key_to_use = os.getenv('API_FOOTBALL_KEY')
            if _api_key_to_use:
                logger.info("API Key loaded from API_FOOTBALL_KEY environment variable.")

        if not _api_key_to_use:
            logger.critical("API Key for APIFootball is not configured. Please provide it to the client, "
                            "set it in the database Configuration, or set the API_FOOTBALL_KEY environment variable.")
            raise ValueError("API Key for APIFootball must be configured.")
        
        self.api_key = _api_key_to_use
        logger.debug(f"APIFootballClient initialized with API key ending in '...{self.api_key[-4:] if len(self.api_key) >= 4 else self.api_key}'.")
    
    def _get_error_guidance(self, error_indicator: str) -> str:
        """
        Get contextual error guidance based on error type.
        
        Args:
            error_indicator: Error code, message, or status code as string
            
        Returns:
            Formatted guidance message
        """
        error_lower = str(error_indicator).lower()
        
        if '404' in error_lower or 'not found' in error_lower:
            return (
                "\n\nPossible causes:"
                "\n  • Invalid or expired API key"
                "\n  • API endpoint has changed"
                "\n  • Your plan doesn't have access to this endpoint"
                "\n  • Verify your API key at https://apifootball.com/dashboard"
            )
        elif 'unauthorized' in error_lower or '401' in error_lower:
            return (
                "\n\nAuthentication failed. Please verify:"
                "\n  • API key is correct in .env or database Configuration"
                "\n  • API key hasn't expired"
                "\n  • Account is active at https://apifootball.com/"
            )
        elif '403' in error_lower or 'forbidden' in error_lower:
            return (
                "\n\nAccess denied:"
                "\n  • Your plan may not include access to this endpoint"
                "\n  • Check subscription limits at https://apifootball.com/pricing"
            )
        elif 'limit' in error_lower or 'quota' in error_lower or '429' in error_lower:
            return (
                "\n\nAPI rate limit or quota exceeded:"
                "\n  • Check your plan limits at https://apifootball.com/dashboard"
                "\n  • Wait before retrying"
                "\n  • Consider upgrading your plan"
            )
        elif any(code in error_lower for code in ['500', '501', '502', '503', '504']):
            return (
                "\n\nServer error:"
                "\n  • APIFootball service is experiencing issues"
                "\n  • Check status at https://apifootball.com/"
                "\n  • This is temporary, retry later"
            )
        return ""
    
    def _sanitize_response_body(self, response_text: str, max_length: int = 500) -> str:
        """
        Sanitize response body by removing potentially sensitive information.
        
        Args:
            response_text: Raw response text
            max_length: Maximum length to return
            
        Returns:
            Sanitized response text
        """
        import re
        
        # Truncate to max length
        text = response_text[:max_length]
        
        # Remove potential API keys (sequences of 20+ alphanumeric characters)
        text = re.sub(r'\b[a-zA-Z0-9]{20,}\b', '[REDACTED]', text)
        
        # Remove potential tokens/passwords in common formats
        text = re.sub(r'(token|key|password|secret|auth)["\s:=]+[a-zA-Z0-9+/=]{10,}', r'\1=[REDACTED]', text, flags=re.IGNORECASE)
        
        return text

    def _request(self, params: Dict) -> Union[Dict, List]:
        """Internal method to handle all API requests with retry logic."""
        url = APIFOOTBALL_BASE_URL
        
        request_params = params.copy() if params else {}
        request_params['APIkey'] = self.api_key
        
        # Log the request without the API key
        logged_params = {k: v for k, v in request_params.items() if k != 'APIkey'}
        logger.info(f"APIFootball Request: URL='{url}', Params={logged_params}")
        
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, params=request_params, timeout=DEFAULT_TIMEOUT)
                
                # Check for rate limiting or error responses
                if response.status_code == 429:
                    logger.warning(f"Rate limit reached. Attempt {attempt + 1}/{MAX_RETRIES}")
                    if attempt < MAX_RETRIES - 1:
                        import time
                        time.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                
                response.raise_for_status()
                
                data = response.json()
                
                # Check for API-specific error messages
                if isinstance(data, dict):
                    if data.get('error'):
                        error_msg = data.get('error', 'Unknown error')
                        additional_info = self._get_error_guidance(error_msg)
                        
                        logger.error(
                            f"APIFootball error response: {error_msg}"
                            f"\nResponse body: {self._sanitize_response_body(response.text)}"
                            f"{additional_info}"
                        )
                        raise APIFootballException(
                            f"API returned error: {error_msg}{additional_info}",
                            response.status_code,
                            response.text,
                            data
                        )
                    # Some endpoints return error code in different format
                    if data.get('message') and 'error' in str(data.get('message')).lower():
                        additional_info = self._get_error_guidance(data.get('message'))
                        logger.error(
                            f"APIFootball error message: {data.get('message')}"
                            f"\nResponse body: {self._sanitize_response_body(response.text)}"
                            f"{additional_info}"
                        )
                        raise APIFootballException(
                            f"API error: {data.get('message')}{additional_info}",
                            response.status_code,
                            response.text,
                            data
                        )
                
                logger.debug(f"APIFootball Response: Status={response.status_code}, Data length={len(str(data))}")
                return data

            except requests.exceptions.HTTPError as e:
                status_code = getattr(e.response, 'status_code', None)
                response_text = getattr(e.response, 'text', "No response body")
                
                try:
                    response_json = e.response.json() if e.response and e.response.text else None
                except ValueError:
                    response_json = None
                
                # Get guidance based on status code
                guidance = self._get_error_guidance(str(status_code)) if status_code else ""
                
                # Sanitize response for logging
                sanitized_response = self._sanitize_response_body(response_text, max_length=400)
                
                log_message = (
                    f"APIFootball HTTPError: {e}. Status: {status_code}. "
                    f"Response: '{sanitized_response}{'...' if len(response_text) > 400 else ''}'"
                    f"{guidance}"
                )
                logger.warning(log_message)
                
                if attempt < MAX_RETRIES - 1:
                    import time
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                
                raise APIFootballException(
                    f"HTTP error: {e}{guidance}", status_code, response_text, response_json
                ) from e
                
            except requests.exceptions.RequestException as e:
                logger.error(f"APIFootball RequestException: {e}")
                if attempt < MAX_RETRIES - 1:
                    import time
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise APIFootballException(f"Request failed: {e}") from e

    def get_countries(self) -> List[dict]:
        """Get list of all available countries."""
        params = {'action': 'get_countries'}
        return self._request(params)

    def get_leagues(self, country_id: Optional[str] = None) -> List[dict]:
        """
        Get list of available leagues.
        
        Args:
            country_id: Optional country ID to filter leagues
            
        Returns:
            List of league dictionaries with structure:
            {
                'country_id': str,
                'country_name': str,
                'league_id': str,
                'league_name': str,
                'league_season': str,
                'league_logo': str
            }
        """
        params = {'action': 'get_leagues'}
        if country_id:
            params['country_id'] = country_id
        return self._request(params)

    def get_fixtures(
        self,
        league_id: Optional[str] = None,
        match_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        team_id: Optional[str] = None
    ) -> List[dict]:
        """
        Get fixtures/matches.
        
        Args:
            league_id: League ID to filter fixtures
            match_id: Specific match ID
            date_from: Start date (YYYY-MM-DD format)
            date_to: End date (YYYY-MM-DD format)
            team_id: Filter by team ID
            
        Returns:
            List of fixture dictionaries
        """
        params = {'action': 'get_events'}
        
        if match_id:
            params['match_id'] = match_id
        if league_id:
            params['league_id'] = league_id
        if date_from:
            params['from'] = date_from
        if date_to:
            params['to'] = date_to
        if team_id:
            params['team_id'] = team_id
            
        return self._request(params)

    def get_upcoming_fixtures(
        self,
        league_id: str,
        days_ahead: int = 7
    ) -> List[dict]:
        """
        Get upcoming fixtures for a league within specified days.
        
        Args:
            league_id: League ID
            days_ahead: Number of days to look ahead (default 7)
            
        Returns:
            List of upcoming fixtures
        """
        date_from = datetime.now().strftime('%Y-%m-%d')
        date_to = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        
        return self.get_fixtures(
            league_id=league_id,
            date_from=date_from,
            date_to=date_to
        )

    def get_live_scores(self) -> List[dict]:
        """
        Get all live scores.
        
        Returns:
            List of live match dictionaries
        """
        params = {'action': 'get_events', 'match_live': '1'}
        return self._request(params)

    def get_finished_matches(
        self,
        league_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[dict]:
        """
        Get finished matches with scores.
        
        Args:
            league_id: Optional league ID
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            
        Returns:
            List of finished matches
        """
        params = {'action': 'get_events'}
        
        if league_id:
            params['league_id'] = league_id
        if date_from:
            params['from'] = date_from
        if date_to:
            params['to'] = date_to
            
        data = self._request(params)
        
        # Filter only finished matches
        if isinstance(data, list):
            return [match for match in data if match.get('match_status') == 'Finished']
        return []

    def get_odds(
        self,
        match_id: Optional[str] = None,
        league_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[dict]:
        """
        Get odds for matches.
        
        Args:
            match_id: Specific match ID
            league_id: League ID to filter
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            
        Returns:
            List of odds dictionaries with structure containing match_id and odds data
        """
        params = {'action': 'get_odds'}
        
        if match_id:
            params['match_id'] = match_id
        if league_id:
            params['league_id'] = league_id
        if date_from:
            params['from'] = date_from
        if date_to:
            params['to'] = date_to
            
        return self._request(params)

    def get_match_odds(self, match_id: str) -> Optional[dict]:
        """
        Get odds for a specific match.
        
        Args:
            match_id: Match ID
            
        Returns:
            Odds dictionary for the match or None if not found
        """
        try:
            odds_list = self.get_odds(match_id=match_id)
            if odds_list and len(odds_list) > 0:
                return odds_list[0]
            return None
        except APIFootballException as e:
            if e.status_code == 404:
                logger.info(f"No odds found for match {match_id} (404 Not Found).")
                return None
            raise

    def get_standings(
        self,
        league_id: str
    ) -> List[dict]:
        """
        Get league standings/table.
        
        Args:
            league_id: League ID
            
        Returns:
            List of standings data
        """
        params = {
            'action': 'get_standings',
            'league_id': league_id
        }
        return self._request(params)

    def get_teams(
        self,
        league_id: Optional[str] = None,
        team_id: Optional[str] = None
    ) -> List[dict]:
        """
        Get teams information.
        
        Args:
            league_id: Optional league ID to filter teams
            team_id: Optional specific team ID
            
        Returns:
            List of team dictionaries
        """
        params = {'action': 'get_teams'}
        
        if league_id:
            params['league_id'] = league_id
        if team_id:
            params['team_id'] = team_id
            
        return self._request(params)

    def get_h2h(
        self,
        first_team_id: str,
        second_team_id: str
    ) -> List[dict]:
        """
        Get head-to-head matches between two teams.
        
        Args:
            first_team_id: First team ID
            second_team_id: Second team ID
            
        Returns:
            List of H2H match records
        """
        params = {
            'action': 'get_H2H',
            'firstTeamId': first_team_id,
            'secondTeamId': second_team_id
        }
        return self._request(params)

    def get_predictions(
        self,
        match_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[dict]:
        """
        Get match predictions (if available in your plan).
        
        Args:
            match_id: Specific match ID
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            
        Returns:
            List of prediction data
        """
        params = {'action': 'get_predictions'}
        
        if match_id:
            params['match_id'] = match_id
        if date_from:
            params['from'] = date_from
        if date_to:
            params['to'] = date_to
            
        return self._request(params)
