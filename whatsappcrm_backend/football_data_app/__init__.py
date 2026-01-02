# Import all tasks to make them discoverable by Celery autodiscovery
# This ensures tasks from both legacy and new API-Football v3 implementations are registered

# Import tasks for Celery autodiscovery
default_app_config = 'football_data_app.apps.FootballDataAppConfig'

# Import tasks from tasks_api_football_v3.py to ensure they are registered
# These tasks are for the new API-Football v3 provider (api-football.com)
try:
    from .tasks_api_football_v3 import (
        run_api_football_v3_full_update,
        fetch_and_update_leagues_v3_task,
        fetch_events_for_league_v3_task,
        fetch_odds_for_single_event_v3_task,
        _prepare_and_launch_event_odds_chord_v3,
        dispatch_odds_fetching_after_events_v3_task,
        run_score_and_settlement_v3_task,
        fetch_scores_for_league_v3_task,
    )
except ImportError:
    pass  # Tasks may not be available in all environments

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
except ImportError:
    pass  # Tasks may not be available in all environments
