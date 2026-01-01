# football_data_app/api_football_v3_client.py
"""
Client for API-Football v3 (api-football.com / api-sports.io)
Documentation: https://www.api-football.com/documentation-v3
"""
import os
import requests
import logging
import time
from typing import List, Optional, Dict, Union, Any
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

# API-Football v3 base URL
API_FOOTBALL_V3_BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class APIFootballV3Exception(Exception):
    """Custom exception for API-Football v3 client errors."""
    def __init__(self, message, status_code=None, response_text=None, response_json=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text
        self.response_json = response_json


class APIFootballV3Client:
    """
    A robust client for making requests to API-Football v3 (api-football.com).
    
    This client uses the api-sports.io infrastructure with x-apisports-key authentication.
    Documentation: https://www.api-football.com/documentation-v3
    """
    
    def __init__(self, api_key: Optional[str] = None):
        _api_key_to_use = api_key
        _api_key_source = None

        if api_key:
            _api_key_source = "constructor parameter"
        else:
            try:
                # Local import to avoid issues if Django isn't fully configured when module is loaded
                from football_data_app.models import Configuration
                config = Configuration.objects.filter(
                    provider_name="API-Football"
                ).first()
                if config and config.api_key:
                    _api_key_to_use = config.api_key
                    _api_key_source = "database Configuration (provider_name='API-Football')"
                    logger.info(f"✓ API Key loaded from {_api_key_source}")
                else:
                    logger.info(
                        "No 'API-Football' configuration found in database, or API key is missing in the config. "
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
            _api_key_to_use = os.getenv('API_FOOTBALL_V3_KEY')
            if _api_key_to_use:
                _api_key_source = "API_FOOTBALL_V3_KEY environment variable"
                logger.info(f"✓ API Key loaded from {_api_key_source}")

        if not _api_key_to_use:
            logger.critical("API Key for API-Football v3 is not configured. Please provide it to the client, "
                            "set it in the database Configuration, or set the API_FOOTBALL_V3_KEY environment variable.")
            raise ValueError("API Key for API-Football v3 must be configured.")
        
        self.api_key = _api_key_to_use
        self.base_url = API_FOOTBALL_V3_BASE_URL
        
        # Log key source and masked key for verification
        key_suffix = self.api_key[-4:] if len(self.api_key) >= 4 else self.api_key
        logger.info(f"✓ APIFootballV3Client initialized successfully")
        logger.info(f"  → Source: {_api_key_source}")
        logger.info(f"  → Key (last 4 chars): ...{key_suffix}")
        logger.debug(f"  → Key length: {len(self.api_key)} characters")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with API key authentication."""
        return {
            'x-apisports-key': self.api_key,
            'Accept': 'application/json'
        }
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Internal method to handle all API requests with retry logic."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Log the request without the API key
        logger.info(f"API-Football v3 Request: URL='{url}', Params={params}")
        
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=DEFAULT_TIMEOUT
                )
                
                # Check for rate limiting or error responses
                if response.status_code == 429:
                    logger.warning(f"Rate limit reached. Attempt {attempt + 1}/{MAX_RETRIES}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                
                response.raise_for_status()
                
                data = response.json()
                
                # API-Football v3 response structure: {"get": "", "parameters": {}, "errors": [], "results": 0, "paging": {}, "response": []}
                if 'errors' in data and data['errors']:
                    error_msg = data['errors']
                    logger.error(f"API-Football v3 error response: {error_msg}")
                    raise APIFootballV3Exception(
                        f"API returned errors: {error_msg}",
                        response.status_code,
                        response.text,
                        data
                    )
                
                logger.debug(f"API-Football v3 Response: Status={response.status_code}, Results={data.get('results', 0)}")
                return data

            except requests.exceptions.HTTPError as e:
                status_code = getattr(e.response, 'status_code', None)
                response_text = getattr(e.response, 'text', "No response body")
                
                try:
                    response_json = e.response.json() if e.response and e.response.text else None
                except ValueError:
                    response_json = None
                
                log_message = f"API-Football v3 HTTPError: {e}. Status: {status_code}"
                logger.warning(log_message)
                
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                
                raise APIFootballV3Exception(
                    f"HTTP error: {e}", status_code, response_text, response_json
                ) from e
                
            except requests.exceptions.RequestException as e:
                logger.error(f"API-Football v3 RequestException: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise APIFootballV3Exception(f"Request failed: {e}") from e

    def get_leagues(
        self,
        league_id: Optional[int] = None,
        country: Optional[str] = None,
        season: Optional[int] = None
    ) -> List[dict]:
        """
        Get available leagues.
        
        Args:
            league_id: Specific league ID
            country: Country name
            season: Season year (e.g., 2023)
            
        Returns:
            List of league dictionaries from response['response']
        """
        params = {}
        if league_id:
            params['id'] = league_id
        if country:
            params['country'] = country
        if season:
            params['season'] = season
            
        response = self._request('leagues', params)
        return response.get('response', [])

    def get_fixtures(
        self,
        fixture_id: Optional[int] = None,
        league_id: Optional[int] = None,
        season: Optional[int] = None,
        date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        team_id: Optional[int] = None,
        status: Optional[str] = None,
        timezone: str = "UTC"
    ) -> List[dict]:
        """
        Get fixtures/matches.
        
        Args:
            fixture_id: Specific fixture ID
            league_id: League ID to filter fixtures
            season: Season year (e.g., 2023)
            date: Specific date (YYYY-MM-DD format)
            date_from: Start date (YYYY-MM-DD format)
            date_to: End date (YYYY-MM-DD format)
            team_id: Filter by team ID
            status: Fixture status (e.g., 'NS', 'LIVE', 'FT')
            timezone: Timezone for dates (default: UTC)
            
        Returns:
            List of fixture dictionaries from response['response']
        """
        params = {'timezone': timezone}
        
        if fixture_id:
            params['id'] = fixture_id
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if date:
            params['date'] = date
        if date_from:
            params['from'] = date_from
        if date_to:
            params['to'] = date_to
        if team_id:
            params['team'] = team_id
        if status:
            params['status'] = status
            
        response = self._request('fixtures', params)
        return response.get('response', [])

    def get_upcoming_fixtures(
        self,
        league_id: int,
        season: int,
        days_ahead: int = 7
    ) -> List[dict]:
        """
        Get upcoming fixtures for a league within specified days.
        
        Args:
            league_id: League ID
            season: Season year
            days_ahead: Number of days to look ahead (default 7)
            
        Returns:
            List of upcoming fixtures
        """
        date_from = datetime.now().strftime('%Y-%m-%d')
        date_to = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        
        return self.get_fixtures(
            league_id=league_id,
            season=season,
            date_from=date_from,
            date_to=date_to,
            status='NS'  # Not started
        )

    def get_live_fixtures(self) -> List[dict]:
        """
        Get all live fixtures.
        
        Returns:
            List of live fixture dictionaries
        """
        response = self._request('fixtures', {'live': 'all'})
        return response.get('response', [])

    def get_odds(
        self,
        fixture_id: Optional[int] = None,
        league_id: Optional[int] = None,
        season: Optional[int] = None,
        date: Optional[str] = None,
        bookmaker_id: Optional[int] = None,
        bet_id: Optional[int] = None
    ) -> List[dict]:
        """
        Get odds for fixtures.
        
        Args:
            fixture_id: Specific fixture ID
            league_id: League ID to filter
            season: Season year
            date: Specific date (YYYY-MM-DD)
            bookmaker_id: Filter by bookmaker ID
            bet_id: Filter by bet type ID
            
        Returns:
            List of odds dictionaries from response['response']
        """
        params = {}
        
        if fixture_id:
            params['fixture'] = fixture_id
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if date:
            params['date'] = date
        if bookmaker_id:
            params['bookmaker'] = bookmaker_id
        if bet_id:
            params['bet'] = bet_id
            
        response = self._request('odds', params)
        return response.get('response', [])

    def get_fixture_odds(self, fixture_id: int) -> Optional[dict]:
        """
        Get odds for a specific fixture.
        
        Args:
            fixture_id: Fixture ID
            
        Returns:
            Odds dictionary for the fixture or None if not found
        """
        try:
            odds_list = self.get_odds(fixture_id=fixture_id)
            if odds_list:
                return odds_list[0]
            return None
        except APIFootballV3Exception as e:
            if e.status_code == 404:
                logger.info(f"No odds found for fixture {fixture_id} (404 Not Found).")
                return None
            raise

    def get_standings(
        self,
        league_id: int,
        season: int,
        team_id: Optional[int] = None
    ) -> List[dict]:
        """
        Get league standings/table.
        
        Args:
            league_id: League ID (required)
            season: Season year (required)
            team_id: Optional specific team ID
            
        Returns:
            List of standings data from response['response']
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        if team_id:
            params['team'] = team_id
            
        response = self._request('standings', params)
        return response.get('response', [])

    def get_teams(
        self,
        team_id: Optional[int] = None,
        league_id: Optional[int] = None,
        season: Optional[int] = None,
        country: Optional[str] = None
    ) -> List[dict]:
        """
        Get teams information.
        
        Args:
            team_id: Optional specific team ID
            league_id: Optional league ID to filter teams
            season: Season year (required if league_id provided)
            country: Country name
            
        Returns:
            List of team dictionaries from response['response']
        """
        params = {}
        
        if team_id:
            params['id'] = team_id
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if country:
            params['country'] = country
            
        response = self._request('teams', params)
        return response.get('response', [])

    def get_head_to_head(
        self,
        team1_id: int,
        team2_id: int,
        last: Optional[int] = None
    ) -> List[dict]:
        """
        Get head-to-head matches between two teams.
        
        Args:
            team1_id: First team ID
            team2_id: Second team ID
            last: Number of last H2H matches to retrieve
            
        Returns:
            List of H2H fixture records from response['response']
        """
        params = {
            'h2h': f"{team1_id}-{team2_id}"
        }
        
        if last:
            params['last'] = last
            
        response = self._request('fixtures/headtohead', params)
        return response.get('response', [])

    def get_players(
        self,
        player_id: Optional[int] = None,
        team_id: Optional[int] = None,
        league_id: Optional[int] = None,
        season: Optional[int] = None
    ) -> List[dict]:
        """
        Get player statistics.
        
        Args:
            player_id: Specific player ID
            team_id: Filter by team ID
            league_id: Filter by league ID
            season: Season year (required if team_id or league_id provided)
            
        Returns:
            List of player data from response['response']
        """
        params = {}
        
        if player_id:
            params['id'] = player_id
        if team_id:
            params['team'] = team_id
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
            
        response = self._request('players', params)
        return response.get('response', [])

    def get_bookmakers(self) -> List[dict]:
        """
        Get list of available bookmakers.
        
        Returns:
            List of bookmaker dictionaries from response['response']
        """
        response = self._request('odds/bookmakers')
        return response.get('response', [])

    def get_bets(self) -> List[dict]:
        """
        Get list of available bet types.
        
        Returns:
            List of bet type dictionaries from response['response']
        """
        response = self._request('odds/bets')
        return response.get('response', [])
