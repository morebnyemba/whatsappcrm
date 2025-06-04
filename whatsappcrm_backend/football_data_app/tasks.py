from celery import shared_task
from django.conf import settings
import logging
import time # Can be used for staggering task creation if necessary

# Import the utility functions from your app's utils.py
from .utils import (
    run_full_data_update_for_leagues,
    fetch_and_update_leagues,
    fetch_and_update_teams_for_league_season,
    fetch_and_update_fixtures,
    fetch_and_update_odds_for_fixture
)
# Import models if needed for more complex task logic (like in fetch_odds_for_upcoming_fixtures_task)
from .models import FootballFixture
from django.utils import timezone as django_timezone


logger = logging.getLogger(__name__)

# --- Task Definitions ---

@shared_task(bind=True, name='football_data.update_leagues_task', max_retries=3, default_retry_delay=60 * 5) # Retry 3 times, 5 mins apart
def update_leagues_task(self, league_ids=None, country_code=None, season=None):
    """
    Celery task to fetch and update leagues.
    :param league_ids: Optional list of specific league API IDs.
    :param country_code: Optional country code.
    :param season: Optional season year.
    """
    task_id = self.request.id
    logger.info(f"Task update_leagues_task [{task_id}] started. Args: league_ids={league_ids}, country_code={country_code}, season={season}")
    try:
        fetch_and_update_leagues(league_ids=league_ids, country_code=country_code, season=season)
        logger.info(f"Task update_leagues_task [{task_id}] completed successfully.")
        return f"Leagues updated successfully. Task ID: {task_id}"
    except Exception as e:
        logger.error(f"Error in update_leagues_task [{task_id}]: {e}", exc_info=True)
        try:
            self.retry(exc=e) # Celery will use default_retry_delay and max_retries
        except self.MaxRetriesExceededError:
            logger.critical(f"Task update_leagues_task [{task_id}] exceeded max retries. Error: {e}", exc_info=True)
            # Potentially send a notification here
        raise # Re-raise the exception to mark the task as failed if not retrying or retries exhausted

@shared_task(bind=True, name='football_data.update_teams_task', max_retries=3, default_retry_delay=60 * 5)
def update_teams_task(self, league_api_id, season_year):
    """
    Celery task to fetch and update teams for a specific league and season.
    """
    task_id = self.request.id
    logger.info(f"Task update_teams_task [{task_id}] started for league_api_id: {league_api_id}, season: {season_year}")
    try:
        fetch_and_update_teams_for_league_season(league_api_id=league_api_id, season_year=season_year)
        logger.info(f"Task update_teams_task [{task_id}] for league {league_api_id}, season {season_year} completed successfully.")
        return f"Teams for league {league_api_id}, season {season_year} updated. Task ID: {task_id}"
    except Exception as e:
        logger.error(f"Error in update_teams_task [{task_id}] for league {league_api_id}, season {season_year}: {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.critical(f"Task update_teams_task [{task_id}] for league {league_api_id} exceeded max retries. Error: {e}", exc_info=True)
        raise

@shared_task(bind=True, name='football_data.update_fixtures_task', max_retries=3, default_retry_delay=60 * 10) # Longer delay for potentially larger data
def update_fixtures_task(self, league_api_id=None, season_year=None, date_from_str=None, date_to_str=None, fixture_api_ids=None):
    """
    Celery task to fetch and update fixtures.
    """
    task_id = self.request.id
    logger.info(f"Task update_fixtures_task [{task_id}] started. Args: league_api_id={league_api_id}, season_year={season_year}, dates=({date_from_str}-{date_to_str}), fixture_ids={fixture_api_ids}")
    try:
        fetch_and_update_fixtures(
            league_api_id=league_api_id,
            season_year=season_year,
            date_from_str=date_from_str,
            date_to_str=date_to_str,
            fixture_api_ids=fixture_api_ids
        )
        logger.info(f"Task update_fixtures_task [{task_id}] completed successfully.")
        return f"Fixtures updated successfully. Task ID: {task_id}"
    except Exception as e:
        logger.error(f"Error in update_fixtures_task [{task_id}]: {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.critical(f"Task update_fixtures_task [{task_id}] exceeded max retries. Error: {e}", exc_info=True)
        raise

@shared_task(bind=True, name='football_data.update_fixture_odds_task', max_retries=5, default_retry_delay=60 * 2) # More retries, shorter delay for odds
def update_fixture_odds_task(self, fixture_api_id, bookmaker_api_id_filter=None):
    """
    Celery task to fetch and update odds for a specific fixture.
    """
    task_id = self.request.id
    logger.info(f"Task update_fixture_odds_task [{task_id}] started for fixture_api_id: {fixture_api_id}, bookmaker_filter: {bookmaker_api_id_filter}")
    try:
        fetch_and_update_odds_for_fixture(
            fixture_api_id=fixture_api_id,
            bookmaker_api_id_filter=bookmaker_api_id_filter
        )
        logger.info(f"Task update_fixture_odds_task [{task_id}] for fixture {fixture_api_id} completed successfully.")
        return f"Odds for fixture {fixture_api_id} updated. Task ID: {task_id}"
    except Exception as e:
        logger.error(f"Error in update_fixture_odds_task [{task_id}] for fixture {fixture_api_id}: {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.critical(f"Task update_fixture_odds_task [{task_id}] for fixture {fixture_api_id} exceeded max retries. Error: {e}", exc_info=True)
        raise

@shared_task(bind=True, name='football_data.run_full_league_data_update_task', max_retries=2, default_retry_delay=60 * 30) # Fewer retries, longer delay for full orchestrator
def run_full_league_data_update_task(self, league_api_ids, current_season_year, fetch_odds=True):
    """
    Celery task to run the full data update orchestration for specified leagues.
    This task orchestrates calls to other utility functions which have their own retry logic.
    Retries on this orchestrator task itself should be limited.
    :param league_api_ids: List of API IDs for leagues.
    :param current_season_year: The season year (e.g., 2023).
    :param fetch_odds: Boolean, whether to fetch odds.
    """
    task_id = self.request.id
    logger.info(f"Task run_full_league_data_update_task [{task_id}] started. Leagues: {league_api_ids}, Season: {current_season_year}, Fetch Odds: {fetch_odds}")
    if not isinstance(league_api_ids, list) or not league_api_ids:
        logger.error(f"Task run_full_league_data_update_task [{task_id}]: Invalid arguments: league_api_ids must be a non-empty list.")
        return "Invalid arguments: league_api_ids must be a non-empty list."

    try:
        run_full_data_update_for_leagues(
            league_api_ids=league_api_ids,
            current_season_year=current_season_year,
            fetch_odds=fetch_odds
        )
        logger.info(f"Task run_full_league_data_update_task [{task_id}] for leagues {league_api_ids}, season {current_season_year} completed successfully.")
        return f"Full data update for leagues {league_api_ids} completed. Task ID: {task_id}"
    except Exception as e:
        logger.error(f"Error in run_full_league_data_update_task [{task_id}] for leagues {league_api_ids}: {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.critical(f"Task run_full_league_data_update_task [{task_id}] for leagues {league_api_ids} exceeded max retries. Error: {e}", exc_info=True)
        raise

@shared_task(bind=True, name='football_data.fetch_odds_for_upcoming_fixtures_task', max_retries=3, default_retry_delay=60 * 10)
def fetch_odds_for_upcoming_fixtures_task(self, hours_lookahead=24, limit_fixtures=50, stagger_seconds=0.2):
    """
    Identifies upcoming fixtures and queues individual tasks to fetch/update their odds.
    Retries on this task mean retrying the process of identifying and queueing.
    The individual `update_fixture_odds_task` calls have their own retry logic.
    :param hours_lookahead: How many hours into the future to look for fixtures.
    :param limit_fixtures: Max number of fixtures to process in one run of this task.
    :param stagger_seconds: Small delay when queueing multiple tasks to avoid thundering herd on Celery.
    """
    task_id = self.request.id
    logger.info(f"Task fetch_odds_for_upcoming_fixtures_task [{task_id}] started. Lookahead: {hours_lookahead}h, Limit: {limit_fixtures}")

    now = django_timezone.now()
    lookahead_time = now + django_timezone.timedelta(hours=hours_lookahead)

    # Define statuses for "Not Started" or "To Be Defined" or "Postponed"
    # These should match the `status_short` values from api-football.com
    pending_statuses = ['NS', 'TBD', 'PST'] # Not Started, To Be Defined, Postponed

    try:
        upcoming_fixtures = FootballFixture.objects.filter(
            match_date__gte=now,
            match_date__lte=lookahead_time,
            status_short__in=pending_statuses,
            is_result_confirmed=False
        ).select_related('league').order_by('match_date')[:limit_fixtures] # select_related for logging

        if not upcoming_fixtures.exists():
            logger.info(f"Task fetch_odds_for_upcoming_fixtures_task [{task_id}]: No upcoming fixtures found needing odds update.")
            return "No upcoming fixtures found."

        logger.info(f"Task fetch_odds_for_upcoming_fixtures_task [{task_id}]: Found {upcoming_fixtures.count()} upcoming fixtures to queue for odds update.")
        queued_count = 0
        for fixture in upcoming_fixtures:
            logger.debug(f"Task [{task_id}]: Queueing odds fetch for fixture: {fixture.match_api_id} ({fixture.home_team.name if fixture.home_team else 'N/A'} vs {fixture.away_team.name if fixture.away_team else 'N/A'})")
            # Call the specific task for fetching odds for one fixture
            update_fixture_odds_task.delay(fixture_api_id=fixture.match_api_id)
            queued_count += 1
            if stagger_seconds > 0:
                time.sleep(stagger_seconds) # Stagger the creation of tasks

        logger.info(f"Task fetch_odds_for_upcoming_fixtures_task [{task_id}] completed. Queued odds updates for {queued_count} fixtures.")
        return f"Queued odds updates for {queued_count} fixtures. Task ID: {task_id}"
    except Exception as e:
        logger.error(f"Error in fetch_odds_for_upcoming_fixtures_task [{task_id}]: {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.critical(f"Task fetch_odds_for_upcoming_fixtures_task [{task_id}] exceeded max retries. Error: {e}", exc_info=True)
        raise

# --- Celery Beat Schedule (Example - Configure in settings.py) ---
# from celery.schedules import crontab

# CELERY_BEAT_SCHEDULE = {
#     'update-major-leagues-daily': {
#         'task': 'football_data.run_full_league_data_update_task',
#         'schedule': crontab(hour=3, minute=0), # Every day at 3:00 AM
#         # Args: ([list_of_league_api_ids], season_year, fetch_odds_boolean)
#         'args': ([39, 140, 61, 78, 135], 2023, True), # Example: PL, La Liga, Ligue 1, Bundesliga, Serie A for 2023
#         'options': {'expires': 60 * 60 * 4}, # Task expires after 4 hours if not started
#     },
#     'fetch-odds-for-upcoming-fixtures-hourly': {
#         'task': 'football_data.fetch_odds_for_upcoming_fixtures_task',
#         'schedule': crontab(minute=5),  # Every hour at 5 minutes past the hour
#         'args': (24, 100, 0.1), # Lookahead 24 hours, max 100 fixtures, 0.1s stagger
#         'options': {'expires': 60 * 30 }, # Task expires after 30 minutes
#     },
#     # Add more scheduled tasks as needed
#     # e.g., a less frequent task to update all leagues/teams metadata
#     'update-all-leagues-metadata-weekly': {
#         'task': 'football_data.update_leagues_task',
#         'schedule': crontab(hour=0, minute=0, day_of_week='sunday'), # Weekly on Sunday at midnight
#         'kwargs': {'season': 2023}, # Example: pass season as keyword arg if fetching all leagues for a season
#     },
# }