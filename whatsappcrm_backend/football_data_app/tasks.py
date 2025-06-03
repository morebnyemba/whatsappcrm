# whatsappcrm_backend/football_data_app/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import timedelta, datetime
import logging

from .models import FootballFixture # Import from current app's models
from .utils import get_football_data_from_api # Import from current app's utils

logger = logging.getLogger(__name__)

@shared_task(name="football_data_app.update_football_fixtures") # Namespacing task name
def update_football_fixtures_data():
    logger.info("Starting football fixtures data update task (from football_data_app).")
    target_competition_codes = ['PL', 'CL'] # Example

    today = timezone.now().date()
    next_week = today + timedelta(days=7)

    for comp_code in target_competition_codes:
        try:
            # Fetch SCHEDULED
            scheduled_matches_data = get_football_data_from_api(
                competition_code=comp_code,
                date_from=today.isoformat(),
                date_to=next_week.isoformat(),
                status='SCHEDULED'
            )
            for match_data in scheduled_matches_data:
                if not all(k in match_data for k in ['id', 'homeTeam', 'awayTeam', 'utcDate', 'status', 'competition']):
                    logger.warning(f"Skipping match data due to missing keys: {match_data.get('id')}")
                    continue
                FootballFixture.objects.update_or_create(
                    match_api_id=match_data['id'],
                    defaults={
                        'competition_code': match_data.get('competition', {}).get('code', comp_code),
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
            logger.info(f"Updated/Created {len(scheduled_matches_data)} scheduled matches for {comp_code}.")
        except Exception as e:
            logger.error(f"Error processing scheduled matches for {comp_code}: {e}", exc_info=True)

        # Fetch FINISHED
        two_days_ago = today - timedelta(days=2)
        try:
            finished_matches_data = get_football_data_from_api(
                competition_code=comp_code,
                date_from=two_days_ago.isoformat(),
                date_to=today.isoformat(),
                status='FINISHED'
            )
            for match_data in finished_matches_data:
                if not all(k in match_data for k in ['id', 'homeTeam', 'awayTeam', 'utcDate', 'status', 'competition', 'score']):
                    logger.warning(f"Skipping finished match data due to missing keys: {match_data.get('id')}")
                    continue
                FootballFixture.objects.update_or_create(
                    match_api_id=match_data['id'],
                    defaults={
                        'competition_code': match_data.get('competition', {}).get('code', comp_code),
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
            logger.info(f"Updated/Created {len(finished_matches_data)} finished matches for {comp_code}.")
        except Exception as e:
            logger.error(f"Error processing finished matches for {comp_code}: {e}", exc_info=True)
    logger.info("Football fixtures data update task finished (from football_data_app).")