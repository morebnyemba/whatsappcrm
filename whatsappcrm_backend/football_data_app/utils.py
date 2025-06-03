# whatsappcrm_backend/football_data_app/utils.py
import requests
import logging
import os
# from django.conf import settings # Uncomment if you prefer to load API_KEY via Django settings

logger = logging.getLogger(__name__)

def get_football_data_from_api(competition_code=None, date_from=None, date_to=None, status=None):
    api_key = os.getenv('FOOTBALL_DATA_API_KEY')
    if not api_key:
        logger.error("CRITICAL: FOOTBALL_DATA_API_KEY not found. No API call will be made.")
        return []

    try:
        logger.debug("Attempting simple network test to google.com...") # Changed to debug level
        test_response = requests.get("https://www.google.com", timeout=5)
        logger.debug(f"Google.com network test response status: {test_response.status_code}")
    except Exception as e_test:
        logger.error(f"Google.com network test failed: {e_test}", exc_info=True)

    headers = {'X-Auth-Token': api_key}
    base_url = 'https://api.football-data.org/v4/matches'
    
    params = {
        'competitions': competition_code,
        'dateFrom': date_from,
        'dateTo': date_to,
        'status': status
    }
    active_params = {k: v for k, v in params.items() if v is not None}

    log_headers = {'X-Auth-Token': '********' + api_key[-4:] if api_key and len(api_key) > 4 else 'KeyPresent'}
    logger.info(f"Attempting to call football-data.org API. URL: {base_url}, Params: {active_params}, Headers: {log_headers}")

    try:
        response = requests.get(base_url, headers=headers, params=active_params, timeout=15)
        logger.info(f"API Response Status Code: {response.status_code} for {competition_code} {status}")

        if response.status_code == 200:
            try:
                data = response.json()
                matches = data.get('matches', [])
                logger.info(f"API call successful for {competition_code} {status}. Matches received: {len(matches)}")
                if not matches and data is not None:
                     logger.warning(f"API for {competition_code} {status} returned 0 matches. Response data (first 500 chars): {str(data)[:500]}")
                return matches
            except ValueError:
                logger.error(f"Failed to decode JSON response from API for {competition_code} {status}.", exc_info=True)
                logger.error(f"Non-JSON API Response (first 500 chars) for {competition_code} {status}: {response.text[:500]}")
                return []
        elif response.status_code == 403:
            logger.error(f"API call for {competition_code} {status} failed with 403 Forbidden. Check API key and plan. Response: {response.text[:500]}")
            return []
        elif response.status_code == 404:
            logger.error(f"API call for {competition_code} {status} failed with 404 Not Found. Check endpoint/ID. Response: {response.text[:500]}")
            return []
        elif response.status_code == 429:
            logger.error(f"API call for {competition_code} {status} failed with 429 Too Many Requests. Rate limit hit. Response: {response.text[:500]}")
            return []
        else:
            logger.error(f"API call for {competition_code} {status} failed with status {response.status_code}. Response Text: {response.text[:500]}")
            return []
    except requests.exceptions.Timeout:
        logger.error(f"API call for {competition_code} {status} timed out.", exc_info=True)
        return []
    except requests.exceptions.ConnectionError:
        logger.error(f"API call for {competition_code} {status} failed (ConnectionError).", exc_info=True)
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"A requests-library error occurred for {competition_code} {status}: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"An unexpected error occurred during API call for {competition_code} {status}: {e}", exc_info=True)
        return []