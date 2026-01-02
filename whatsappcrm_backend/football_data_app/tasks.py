"""
Football data tasks - API-Football v3 (api-football.com) recommended.

This module imports and re-exports tasks from tasks_apifootball.py for backward compatibility.
The existing implementation uses apifootball.com (without dash), but the system now supports
API-Football v3 (api-football.com with dash) which is the recommended provider.

To use API-Football v3 (api-football.com):
1. Set API_FOOTBALL_V3_KEY in your .env file
2. Create a Configuration entry with provider_name='API-Football'
3. Use the new api_football_v3_client.APIFootballV3Client

Legacy providers (for backward compatibility):
- apifootball.com (without dash): tasks_apifootball.py
- The Odds API: tasks_theoddsapi_backup.py
"""

import logging

# Import all tasks from the new APIFootball implementation
from .tasks_apifootball import (
    # Main pipeline tasks
    run_apifootball_full_update_task,
    fetch_and_update_leagues_task,
    fetch_events_for_league_task,
    fetch_odds_for_single_event_task,
    dispatch_odds_fetching_after_events_task,
    _prepare_and_launch_event_odds_chord,
    
    # Score and settlement tasks
    run_score_and_settlement_task,
    fetch_scores_for_league_task,
    settle_fixture_pipeline_task,
    settle_outcomes_for_fixture_task,
    settle_bets_for_fixture_task,
    settle_tickets_for_fixture_task,
    
    # Ticket settlement tasks
    process_ticket_settlement_task,
    process_ticket_settlement_batch_task,
    reconcile_and_settle_pending_items_task,
    send_bet_ticket_settlement_notification_task,
)

# Import API-Football v3 tasks (optional, will not fail if not available)
try:
    from .tasks_api_football_v3 import (
        run_api_football_v3_full_update_task,
        run_score_and_settlement_v3_task,
    )
    HAS_V3_TASKS = True
except ImportError:
    HAS_V3_TASKS = False

logger = logging.getLogger(__name__)

# Re-export main entry point with original name for backward compatibility
run_the_odds_api_full_update = run_apifootball_full_update_task
run_the_odds_api_full_update_task = run_apifootball_full_update_task

# Log the transition
logger.info("Football data tasks: API-Football v3 (api-football.com) is now the recommended provider.")
logger.info("Legacy provider (apifootball.com without dash) tasks are still available for backward compatibility.")
if HAS_V3_TASKS:
    logger.info("API-Football v3 tasks successfully loaded and available.")

# Make all tasks available for import
__all__ = [
    'run_apifootball_full_update_task',
    'run_the_odds_api_full_update',
    'run_the_odds_api_full_update_task',
    'fetch_and_update_leagues_task',
    'fetch_events_for_league_task',
    'fetch_odds_for_single_event_task',
    'dispatch_odds_fetching_after_events_task',
    '_prepare_and_launch_event_odds_chord',
    'run_score_and_settlement_task',
    'fetch_scores_for_league_task',
    'settle_fixture_pipeline_task',
    'settle_outcomes_for_fixture_task',
    'settle_bets_for_fixture_task',
    'settle_tickets_for_fixture_task',
    'process_ticket_settlement_task',
    'process_ticket_settlement_batch_task',
    'reconcile_and_settle_pending_items_task',
    'send_bet_ticket_settlement_notification_task',
]

# Add v3 tasks to exports if available
if HAS_V3_TASKS:
    __all__.extend([
        'run_api_football_v3_full_update_task',
        'run_score_and_settlement_v3_task',
    ])
