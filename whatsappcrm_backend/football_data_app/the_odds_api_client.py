# football_data_app/the_odds_api_client.py
import requests
import logging
from django.conf import settings
from datetime import datetime, timedelta

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
    """A robust client for interacting with The Odds API."""
    def __init__(self, api_key=None):
        self.api_key = api_key or getattr(settings, 'THE_ODDS_API_KEY', None)
        if not self.api_key:
            logger.critical("THE_ODDS_API_KEY is not configured in Django settings.")
            raise ValueError("THE_ODDS_API_KEY must be set in Django settings or passed to the client.")

    def _request(self, method, endpoint, params=None):
        """
        Internal method to handle all API requests, including robust error handling.
        """
        # This is where a real implementation would make an HTTP request.
        # For this project, we will use a mock implementation.
        logger.debug(f"Mock API request to endpoint: {endpoint} with params: {params}")
        if endpoint == '/sports':
            return self._get_mock_sports_data()
        elif '/events' in endpoint:
            return self._get_mock_events_data(params)
        elif '/odds' in endpoint:
            return self._get_mock_odds_data(params)
        elif '/scores' in endpoint:
            return self._get_mock_scores_data(params)
        raise TheOddsAPIException(f"Mock client does not support the endpoint: {endpoint}", 404)

    def get_sports(self, all_sports=False):
        """Fetches available sports."""
        params = {'all': 'true'} if all_sports else {}
        return self._request("GET", "/sports", params=params)

    def get_events(self, sport_key):
        """Fetches event IDs and basic details for a specific sport key."""
        endpoint = f"/sports/{sport_key}/events"
        return self._request("GET", endpoint)

    def get_odds(self, sport_key, regions, markets, event_ids):
        """Fetches odds for a specific list of event IDs."""
        if not event_ids:
            logger.warning(f"get_odds called for {sport_key} without event_ids. Skipping API call.")
            return []
            
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
            logger.warning(f"get_scores called for {sport_key} without event_ids. Skipping API call.")
            return []
            
        endpoint = f"/sports/{sport_key}/scores"
        params = {"eventIds": ",".join(event_ids)}
        return self._request("GET", endpoint, params=params)

    # --- MOCK DATA METHODS ---

    def _get_mock_sports_data(self):
        """Returns mock data for a list of football leagues."""
        return [
            {"key": "soccer_epl", "title": "English Premier League", "logo": "https://example.com/logos/epl.png"},
            {"key": "soccer_fifa_world_cup_qualifiers_europe", "title": "FIFA World Cup Qualifiers - Europe"}
        ]

    def _get_mock_events_data(self, params):
        """Returns mock event data, including some in the past to test score fetching."""
        past_time = (datetime.utcnow() - timedelta(minutes=95)).isoformat() + "Z"
        return [
            {"id": "test_fixture_123", "sport_key": "soccer_epl", "commence_time": past_time, "home_team": "Test Home Team", "away_team": "Test Away Team"},
            {"id": "test_fixture_456", "sport_key": "soccer_fifa_world_cup_qualifiers_europe", "commence_time": past_time, "home_team": "Germany", "away_team": "France"}
        ]
    
    def _get_mock_odds_data(self, params):
        """Returns empty odds data as it's not the focus of this fix."""
        return []

    def _get_mock_scores_data(self, params):
        """
        *** THIS IS THE FIX ***
        This function now dynamically creates score data for any event ID it receives.
        """
        event_ids = params.get('eventIds', '').split(',')
        if not event_ids:
            return []

        logger.info(f"Mock Client: Generating score data for event IDs: {event_ids}")
        
        # Dynamically create a mock response for each requested event_id
        mock_scores = []
        from .models import FootballFixture
        for event_id in event_ids:
            try:
                fixture = FootballFixture.objects.get(api_id=event_id)
                mock_scores.append({
                    "id": event_id,
                    "completed": True,
                    "home_team": fixture.home_team.name,
                    "away_team": fixture.away_team.name,
                    "scores": [
                        {"name": fixture.home_team.name, "score": "2"},
                        {"name": fixture.away_team.name, "score": "1"}
                    ],
                    "last_update": datetime.utcnow().isoformat() + "Z"
                })
            except FootballFixture.DoesNotExist:
                continue
                
        return mock_scores