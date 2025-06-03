# football_data_app/utils.py
import requests
import logging
import os
# from django.conf import settings # Uncomment if you prefer to load API_KEY via Django settings

logger = logging.getLogger(__name__)

def get_football_data_from_api(competition_code=None, date_from=None, date_to=None, status=None):
    """
    Fetches football data from the football-data.org API with comprehensive logging.
    """
    # --- 1. Load API Key ---
    api_key = os.getenv('FOOTBALL_DATA_API_KEY')
    # Alternatively, load via Django settings if configured there:
    # from django.conf import settings
    # api_key = settings.FOOTBALL_DATA_API_KEY # Ensure FOOTBALL_DATA_API_KEY is defined in your settings

    if not api_key:
        logger.error("CRITICAL: FOOTBALL_DATA_API_KEY not found in environment variables or settings. No API call will be made.")
        return []

    # --- 2. Simple Network Test (Optional - for debugging container connectivity) ---
    # You can comment this out once you've confirmed general network connectivity
    try:
        logger.info("Attempting simple network test to google.com...")
        test_response = requests.get("https://www.google.com", timeout=5)
        logger.info(f"Google.com network test response status: {test_response.status_code}")
    except Exception as e_test:
        logger.error(f"Google.com network test failed: {e_test}", exc_info=True)
        # Depending on strictness, you might want to return [] here if basic connectivity fails
        # return [] 

    # --- 3. Prepare API Call Details ---
    headers = {'X-Auth-Token': api_key}
    base_url = 'https://api.football-data.org/v4/matches' # Ensure API version v4 is correct for your key/plan
    
    # Prepare parameters, removing any that are None to avoid issues with the API
    params = {
        'competitions': competition_code,
        'dateFrom': date_from,
        'dateTo': date_to,
        'status': status
    }
    active_params = {k: v for k, v in params.items() if v is not None}

    # Log the attempt, but be careful not to log the full API key directly in production logs
    # For debugging, you might temporarily log more, but remove it later.
    log_headers = {'X-Auth-Token': '********' + api_key[-4:] if api_key and len(api_key) > 4 else 'KeyPresent'}
    logger.info(f"Attempting to call football-data.org API. URL: {base_url}, Params: {active_params}, Headers: {log_headers}")

    # --- 4. Make API Call with Error Handling ---
    try:
        response = requests.get(base_url, headers=headers, params=active_params, timeout=15) # Timeout in seconds
        logger.info(f"API Response Status Code: {response.status_code}")

        if response.status_code == 200:
            try:
                data = response.json()
                matches = data.get('matches', [])
                logger.info(f"API call successful. Matches received: {len(matches)}")
                if not matches and data is not None: # Check if data itself is None too
                     logger.warning(f"API returned 0 matches, but response was not empty. Response data (first 500 chars): {str(data)[:500]}")
                return matches
            except ValueError: # Includes JSONDecodeError
                logger.error("Failed to decode JSON response from API.", exc_info=True)
                logger.error(f"Non-JSON API Response (first 500 chars): {response.text[:500]}")
                return []
        elif response.status_code == 403:
            logger.error(f"API call failed with status 403 Forbidden. Check your API key and subscription plan for this competition/endpoint. Response: {response.text[:500]}")
            return []
        elif response.status_code == 404:
            logger.error(f"API call failed with status 404 Not Found. Check the API endpoint or competition ID. Response: {response.text[:500]}")
            return []
        elif response.status_code == 429:
            logger.error(f"API call failed with status 429 Too Many Requests. You've hit a rate limit. Response: {response.text[:500]}")
            return []
        else:
            logger.error(f"API call failed with status {response.status_code}. Response Text (first 500 chars): {response.text[:500]}")
            return []

    except requests.exceptions.Timeout:
        logger.error("API call timed out after 15 seconds.", exc_info=True)
        return []
    except requests.exceptions.ConnectionError:
        logger.error("API call failed due to a connection error (e.g., DNS failure, refused connection). Check network.", exc_info=True)
        return []
    except requests.exceptions.RequestException as e: # Catches other requests-related errors
        logger.error(f"A requests-library related error occurred: {e}", exc_info=True)
        return []
    except Exception as e: # General fallback for any other unexpected errors
        logger.error(f"An unexpected error occurred during the API call: {e}", exc_info=True)
        return []

# Example of how this might be called from your tasks.py (for context)
# if __name__ == '__main__':
#    # This part is for direct testing of this file, requires .env to be loadable here
#    # or api_key to be hardcoded temporarily for the test.
#    # Ensure FOOTBALL_DATA_API_KEY is set as an environment variable for this direct test.
#    print("Testing get_football_data_from_api function...")
#    # Test with a league you have access to and expect data for (e.g., BSA, or use past dates for PL/CL)
#    # test_matches = get_football_data_from_api(competition_code='BSA', status='SCHEDULED') 
#    # Past PL dates:
#    # test_matches = get_football_data_from_api(competition_code='PL', status='FINISHED', date_from='2024-05-01', date_to='2024-05-07')
#    # print(f"Found {len(test_matches)} matches.")
#    # if test_matches:
#    #     print("First match:", test_matches[0])
