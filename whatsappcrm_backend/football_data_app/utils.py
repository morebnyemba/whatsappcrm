# whatsappcrm_backend/football_data_app/utils.py
import requests
import logging
from django.conf import settings # To get API key if stored there

logger = logging.getLogger(__name__)

def get_football_data_from_api(competition_code=None, date_from=None, date_to=None, status=None):
    # Retrieve your API key securely (e.g., from .env via settings)
    # api_key = os.getenv('FOOTBALL_DATA_API_KEY')
    # if not api_key:
    #     logger.error("FOOTBALL_DATA_API_KEY not found in environment variables.")
    #     return []
    # headers = {'X-Auth-Token': api_key}

    # This is a placeholder. Use your actual API key retrieval and error handling.
    # For testing, you might temporarily hardcode, but move to .env for production.
    api_key = "926292af210140c0a2cd076e6b4dcee0" # Replace with your key or load from env
    if api_key == "YOUR_FOOTBALL_DATA_ORG_API_KEY":
         logger.warning("Using a placeholder API key for football-data.org. Please configure properly.")

    headers = {'X-Auth-Token': api_key}
    base_url = 'https://api.football-data.org/v4/matches'
    params = {}
    if competition_code:
        # The API expects competitions to be a comma-separated string if filtering by it directly in /matches
        # or you can use the /competitions/{id}/matches endpoint
        params['competitions'] = competition_code 
    if date_from:
        params['dateFrom'] = date_from
    if date_to:
        params['dateTo'] = date_to
    if status:
        params['status'] = status

    try:
        response = requests.get(base_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('matches', [])
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error fetching football data: {e.response.status_code} - {e.response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request exception fetching football data: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching football data: {e}", exc_info=True)
    return []