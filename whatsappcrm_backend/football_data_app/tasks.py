# whatsappcrm_backend/football_data_app/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import datetime, timedelta
import logging
# import time # Not strictly needed if processing one league and Beat schedule is adjusted

from .models import FootballFixture, FootballTaskRunState
from .utils import get_football_data_from_api

logger = logging.getLogger(__name__)

# Define your full list of target competition codes here.
# These are the leagues from your football-data.org account screenshot.
# Example: ['WC', 'CL', 'BL1', 'DED', 'BSA', 'PD', 'FL1', 'ELC', 'PPL', 'EC', 'SA', 'PL']
# For initial, safer testing, you might start with fewer.
ALL_COMPETITION_CODES = ['WC', 'CL', 'BL1', 'DED', 'BSA', 'PD', 'FL1', 'ELC', 'PPL', 'EC', 'SA', 'PL']

@shared_task(name="football_data_app.update_football_fixtures")
def update_football_fixtures_data():
    logger.info("Starting football fixtures data update task (cycling one league per run).")

    if not ALL_COMPETITION_CODES:
        logger.warning("ALL_COMPETITION_CODES list in tasks.py is empty. No leagues to process.")
        return

    # Get or create the state tracker for this task
    task_state, _ = FootballTaskRunState.objects.get_or_create(
        task_marker="update_football_fixtures_state"
    )

    # Determine the next league to process
    current_stored_index = task_state.last_processed_league_index
    next_index_to_process = (current_stored_index + 1) % len(ALL_COMPETITION_CODES)
    comp_code_to_process = ALL_COMPETITION_CODES[next_index_to_process]

    logger.info(f"This run will process league: {comp_code_to_process} (Index: {next_index_to_process} of {len(ALL_COMPETITION_CODES)-1})")

    # Dates for API calls
    today_iso = timezone.now().date().isoformat()
    next_week_iso = (timezone.now().date() + timedelta(days=7)).isoformat()
    # For finished matches, using dates from your logs that yielded BSA data
    # Adjust these if you want to test other specific past periods or current "last 2 days"
    finished_date_from = (timezone.now().date() - timedelta(days=2)).isoformat() # "2025-06-01" in your logs
    finished_date_to = today_iso # "2025-06-03" in your logs

    # --- Fetch SCHEDULED Matches for the selected league ---
    logger.info(f"Fetching SCHEDULED matches for {comp_code_to_process} from {today_iso} to {next_week_iso}")
    scheduled_matches_data = get_football_data_from_api(
        competition_code=comp_code_to_process,
        date_from=today_iso,
        date_to=next_week_iso,
        status='SCHEDULED'
    )
    s_created, s_updated = 0, 0
    if scheduled_matches_data:
        for match_data in scheduled_matches_data:
            if not all(k in match_data for k in ['id', 'homeTeam', 'awayTeam', 'utcDate', 'status', 'competition']):
                logger.warning(f"Skipping scheduled match data for {comp_code_to_process} (ID: {match_data.get('id')}) due to missing keys.")
                continue
            try:
                obj, created = FootballFixture.objects.update_or_create(
                    match_api_id=match_data['id'],
                    defaults={
                        'competition_code': match_data.get('competition', {}).get('code', comp_code_to_process),
                        'competition_name': match_data.get('competition', {}).get('name'),
                        'home_team_name': match_data.get('homeTeam', {}).get('name', 'TBC'),
                        'home_team_short_name': match_data.get('homeTeam', {}).get('shortName'),
                        'away_team_name': match_data.get('awayTeam', {}).get('name', 'TBC'),
                        'away_team_short_name': match_data.get('awayTeam', {}).get('shortName'),
                        'match_datetime_utc': datetime.fromisoformat(match_data['utcDate'].replace('Z', '+00:00')),
                        'status': match_data['status'],
                        'last_api_update': timezone.now()
                    }
                )
                if created: s_created += 1
                else: s_updated += 1
            except Exception as e:
                logger.error(f"Error saving scheduled match {match_data.get('id')} for {comp_code_to_process}: {e}", exc_info=True)
    logger.info(f"SCHEDULED for {comp_code_to_process}: API returned {len(scheduled_matches_data if scheduled_matches_data else [])} matches. DB Created: {s_created}, DB Updated: {s_updated}.")

    # --- Fetch FINISHED Matches for the selected league ---
    logger.info(f"Fetching FINISHED matches for {comp_code_to_process} from {finished_date_from} to {finished_date_to}")
    finished_matches_data = get_football_data_from_api(
        competition_code=comp_code_to_process,
        date_from=finished_date_from,
        date_to=finished_date_to,
        status='FINISHED'
    )
    f_created, f_updated = 0, 0
    if finished_matches_data:
        for match_data in finished_matches_data:
            if not all(k in match_data for k in ['id', 'homeTeam', 'awayTeam', 'utcDate', 'status', 'competition', 'score']):
                logger.warning(f"Skipping finished match data for {comp_code_to_process} (ID: {match_data.get('id')}) due to missing keys.")
                continue
            try:
                obj, created = FootballFixture.objects.update_or_create(
                    match_api_id=match_data['id'],
                    defaults={
                        'competition_code': match_data.get('competition', {}).get('code', comp_code_to_process),
                        'competition_name': match_data.get('competition', {}).get('name'),
                        'home_team_name': match_data.get('homeTeam', {}).get('name', 'TBC'),
                        'home_team_short_name': match_data.get('homeTeam', {}).get('shortName'),
                        'away_team_name': match_data.get('awayTeam', {}).get('name', 'TBC'),
                        'away_team_short_name': match_data.get('awayTeam', {}).get('shortName'),
                        'match_datetime_utc': datetime.fromisoformat(match_data['utcDate'].replace('Z', '+00:00')),
                        'status': match_data['status'],
                        'home_score': match_data.get('score', {}).get('fullTime', {}).get('home'),
                        'away_score': match_data.get('score', {}).get('fullTime', {}).get('away'),
                        'winner': match_data.get('score', {}).get('winner'),
                        'last_api_update': timezone.now()
                    }
                )
                if created: f_created += 1
                else: f_updated += 1
            except Exception as e:
                logger.error(f"Error saving finished match {match_data.get('id')} for {comp_code_to_process}: {e}", exc_info=True)
    logger.info(f"FINISHED for {comp_code_to_process}: API returned {len(finished_matches_data if finished_matches_data else [])} matches. DB Created: {f_created}, DB Updated: {f_updated}.")

    # Update the state for the next run
    task_state.last_processed_league_index = next_index_to_process
    # task_state.last_run_at is auto_now, so it will be updated on save.
    task_state.save()

    logger.info(f"Football fixtures data update task finished processing league: {comp_code_to_process}.")