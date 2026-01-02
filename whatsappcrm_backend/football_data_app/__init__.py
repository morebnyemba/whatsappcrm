# Import all tasks to make them discoverable by Celery autodiscovery
# This ensures tasks from both legacy and new API-Football v3 implementations are registered

import logging

logger = logging.getLogger(__name__)

# Import tasks from tasks_api_football_v3.py to ensure they are registered
# These tasks are for the new API-Football v3 provider (api-football.com)
try:
    from .tasks_api_football_v3 import (
        run_api_football_v3_full_update,
        fetch_and_update_leagues_v3_task,
        fetch_events_for_league_v3_task,
        fetch_odds_for_single_event_v3_task,
        # Note: _prepare_and_launch_event_odds_chord_v3 is imported despite being "private"
        # because it's a @shared_task that's called via .s() signature in chains/chords
        # and must be registered with Celery for proper task routing
        _prepare_and_launch_event_odds_chord_v3,
        dispatch_odds_fetching_after_events_v3_task,
        run_score_and_settlement_v3_task,
        fetch_scores_for_league_v3_task,
    )
    logger.debug("Successfully imported API-Football v3 tasks")
except ImportError as e:
    logger.warning(f"Could not import API-Football v3 tasks: {e}. "
                   f"This is expected if dependencies are not installed yet.")

# Import tasks from tasks.py (which re-exports from tasks_apifootball.py)
# These tasks are for the legacy provider compatibility
try:
    from .tasks import (
        run_apifootball_full_update_task,
        run_the_odds_api_full_update_task,
        fetch_and_update_leagues_task,
        fetch_events_for_league_task,
        fetch_odds_for_single_event_task,
        dispatch_odds_fetching_after_events_task,
        run_score_and_settlement_task,
        fetch_scores_for_league_task,
    )
    logger.debug("Successfully imported legacy football tasks")
except ImportError as e:
    logger.warning(f"Could not import legacy football tasks: {e}. "
                   f"This is expected if dependencies are not installed yet.")
