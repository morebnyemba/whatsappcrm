"""
Football data tasks - Now using APIFootball.com by default.

This module imports and re-exports tasks from tasks_apifootball.py for backward compatibility.
To use the old The Odds API, you can still import from tasks_theoddsapi_backup.py directly.
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

logger = logging.getLogger(__name__)

# Re-export main entry point with original name for backward compatibility
run_the_odds_api_full_update = run_apifootball_full_update_task
run_the_odds_api_full_update_task = run_apifootball_full_update_task

# Log the transition
logger.info("Football data tasks now using APIFootball.com as the primary provider.")

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
