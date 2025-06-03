# whatsappcrm_backend/football_data_app/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import datetime, timedelta # Ensure timedelta is imported
import logging

from .models import FootballFixture
from .utils import get_football_data_from_api # Your API utility

logger = logging.getLogger(__name__)

@shared_task(name="football_data_app.update_football_fixtures")
def update_football_fixtures_data():
    logger.info("Starting football fixtures data update task (from football_data_app).")

    # --- Configuration for Testing with Previous Dates ---
    # Set to True to run the test with past dates, False to use normal (current) date logic.
    TEST_WITH_PAST_DATES = False # <-- SET TO True TO TEST PAST DATES, False FOR NORMAL RUN
    
    # Define your test parameters if TEST_WITH_PAST_DATES is True
    TEST_COMPETITION_CODE = 'PL'  # e.g., Premier League. Use a code from your available leagues
    TEST_STATUS = 'FINISHED'      # We want to fetch games that have results.
    # Example: A week in October 2024 (adjust if needed for active season)
    TEST_DATE_FROM = '2024-10-01' 
    TEST_DATE_TO = '2024-10-07'
    # --- End of Test Configuration ---

    if TEST_WITH_PAST_DATES:
        logger.info(f"--- RUNNING IN TEST MODE FOR PAST DATES ---")
        logger.info(f"Attempting to fetch {TEST_STATUS} matches for competition '{TEST_COMPETITION_CODE}' from {TEST_DATE_FROM} to {TEST_DATE_TO}")
        
        matches_data = get_football_data_from_api(
            competition_code=TEST_COMPETITION_CODE,
            date_from=TEST_DATE_FROM,
            date_to=TEST_DATE_TO,
            status=TEST_STATUS
        )

        if matches_data is None: # get_football_data_from_api should return [] on error/no data
            logger.warning("Received None from get_football_data_from_api, expecting a list. Defaulting to empty list.")
            matches_data = []

        count_created = 0
        count_updated = 0
        logger.info(f"Processing {len(matches_data)} matches received from API for {TEST_COMPETITION_CODE} ({TEST_STATUS}).")

        for match_data in matches_data:
            # Basic validation of essential keys
            if not all(k in match_data for k in ['id', 'homeTeam', 'awayTeam', 'utcDate', 'status', 'competition']):
                logger.warning(f"Skipping match data due to missing essential keys: {match_data.get('id', 'ID_UNKNOWN')}")
                continue
            
            # Score data is crucial for 'FINISHED' status
            score_data = match_data.get('score', {})
            full_time_score = score_data.get('fullTime', {})
            home_score_data = full_time_score.get('home') # Could be None if not available
            away_score_data = full_time_score.get('away') # Could be None if not available

            if TEST_STATUS == 'FINISHED' and (home_score_data is None or away_score_data is None):
                 logger.warning(f"Skipping FINISHED match {match_data.get('id')} due to missing fullTime score data. Score object: {score_data}")
                 continue

            try:
                obj, created = FootballFixture.objects.update_or_create(
                    match_api_id=match_data['id'],
                    defaults={
                        'competition_code': match_data.get('competition', {}).get('code', TEST_COMPETITION_CODE),
                        'competition_name': match_data.get('competition', {}).get('name'),
                        'home_team_name': match_data.get('homeTeam', {}).get('name', 'TBC'),
                        'home_team_short_name': match_data.get('homeTeam', {}).get('shortName'),
                        'away_team_name': match_data.get('awayTeam', {}).get('name', 'TBC'),
                        'away_team_short_name': match_data.get('awayTeam', {}).get('shortName'),
                        'match_datetime_utc': datetime.fromisoformat(match_data['utcDate'].replace('Z', '+00:00')),
                        'status': match_data['status'],
                        'home_score': home_score_data,
                        'away_score': away_score_data,
                        'winner': score_data.get('winner'), # Winner might be None too
                        'last_api_update': timezone.now()
                    }
                )
                if created:
                    count_created += 1
                else:
                    count_updated += 1
            except Exception as e_db:
                logger.error(f"Error saving match {match_data.get('id', 'ID_UNKNOWN')} to database: {e_db}", exc_info=True)

        logger.info(f"Test fetch for {TEST_COMPETITION_CODE} ({TEST_STATUS}): API returned {len(matches_data)} matches. DB Created: {count_created}, DB Updated: {count_updated}.")
        logger.info(f"--- FINISHED TEST MODE FOR PAST DATES ---")

    else:
        # --- Normal/Original Logic for Fetching Current/Upcoming Data ---
        logger.info("--- RUNNING IN NORMAL MODE FOR CURRENT/UPCOMING DATES ---")
        # Define competitions to fetch normally (e.g., those your free tier covers and are relevant)
        # Refer to your screenshot for available competition codes
        target_competition_codes = ['PL', 'CL'] # Adjust as needed, e.g., ['BSA', 'WC']

        current_date = timezone.now().date()
        today_iso = current_date.isoformat()
        next_week_iso = (current_date + timedelta(days=7)).isoformat()
        two_days_ago_iso = (current_date - timedelta(days=2)).isoformat()
        
        for comp_code in target_competition_codes:
            # --- Fetch Scheduled Matches ---
            logger.info(f"Fetching SCHEDULED matches for {comp_code} from {today_iso} to {next_week_iso}")
            scheduled_matches_data = get_football_data_from_api(
                competition_code=comp_code,
                date_from=today_iso,
                date_to=next_week_iso,
                status='SCHEDULED'
            )
            if scheduled_matches_data is None: scheduled_matches_data = [] # Ensure list
            
            s_created, s_updated = 0, 0
            for match_data in scheduled_matches_data:
                if not all(k in match_data for k in ['id', 'homeTeam', 'awayTeam', 'utcDate', 'status', 'competition']):
                    logger.warning(f"Skipping scheduled match data due to missing keys: {match_data.get('id')}")
                    continue
                try:
                    obj, created = FootballFixture.objects.update_or_create(
                        match_api_id=match_data['id'],
                        defaults={
                            'competition_code': match_data.get('competition', {}).get('code', comp_code),
                            'competition_name': match_data.get('competition', {}).get('name'),
                            'home_team_name': match_data.get('homeTeam', {}).get('name', 'TBC'),
                            'away_team_name': match_data.get('awayTeam', {}).get('name', 'TBC'),
                            'match_datetime_utc': datetime.fromisoformat(match_data['utcDate'].replace('Z', '+00:00')),
                            'status': match_data['status'],
                            'last_api_update': timezone.now()
                        }
                    )
                    if created: s_created += 1
                    else: s_updated += 1
                except Exception as e_db:
                    logger.error(f"Error saving scheduled match {match_data.get('id')} to database: {e_db}", exc_info=True)
            logger.info(f"SCHEDULED for {comp_code}: API returned {len(scheduled_matches_data)} matches. DB Created: {s_created}, DB Updated: {s_updated}.")

            # --- Fetch Finished Matches ---
            logger.info(f"Fetching FINISHED matches for {comp_code} from {two_days_ago_iso} to {today_iso}")
            finished_matches_data = get_football_data_from_api(
                competition_code=comp_code,
                date_from=two_days_ago_iso,
                date_to=today_iso,
                status='FINISHED'
            )
            if finished_matches_data is None: finished_matches_data = [] # Ensure list

            f_created, f_updated = 0, 0
            for match_data in finished_matches_data:
                if not all(k in match_data for k in ['id', 'homeTeam', 'awayTeam', 'utcDate', 'status', 'competition', 'score']):
                    logger.warning(f"Skipping finished match data due to missing keys: {match_data.get('id')}")
                    continue
                
                score_data = match_data.get('score', {})
                full_time_score = score_data.get('fullTime', {})
                home_score_data = full_time_score.get('home')
                away_score_data = full_time_score.get('away')

                if home_score_data is None or away_score_data is None:
                    logger.warning(f"Skipping FINISHED match {match_data.get('id')} (normal mode) due to missing fullTime score. Score obj: {score_data}")
                    continue
                try:
                    obj, created = FootballFixture.objects.update_or_create(
                        match_api_id=match_data['id'],
                        defaults={
                            'competition_code': match_data.get('competition', {}).get('code', comp_code),
                            'competition_name': match_data.get('competition', {}).get('name'),
                            'home_team_name': match_data.get('homeTeam', {}).get('name', 'TBC'),
                            'away_team_name': match_data.get('awayTeam', {}).get('name', 'TBC'),
                            'match_datetime_utc': datetime.fromisoformat(match_data['utcDate'].replace('Z', '+00:00')),
                            'status': match_data['status'],
                            'home_score': home_score_data,
                            'away_score': away_score_data,
                            'winner': score_data.get('winner'),
                            'last_api_update': timezone.now()
                        }
                    )
                    if created: f_created += 1
                    else: f_updated += 1
                except Exception as e_db:
                    logger.error(f"Error saving finished match {match_data.get('id')} to database: {e_db}", exc_info=True)
            logger.info(f"FINISHED for {comp_code}: API returned {len(finished_matches_data)} matches. DB Created: {f_created}, DB Updated: {f_updated}.")
        logger.info(f"--- FINISHED NORMAL MODE ---")

    logger.info("Football fixtures data update task finished (from football_data_app).")