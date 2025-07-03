# flows/view_results_flow.py

def create_view_results_flow():
    """
    Defines a flow to show all recent match results.
    """
    return {
        "name": "View Football Results",
        "description": "Shows all recent football match results and prompts for next action.",
        "trigger_keywords": ["results", "view results", "scores"],
        "is_active": True,
        "steps": [
            {
                "name": "fetch_all_results",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "fetch_football_data",
                            "data_type": "finished_results",
                            # No league_code_variable, so it fetches for all leagues
                            "output_variable_name": "results_display_parts",
                            "days_past": 2 # Look back 2 days for recent results
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "send_all_results",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "flow_context.results_display_parts"
                        }
                    },
                    {
                        "to_step": "no_results_found",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "send_all_results",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        # The service layer will handle sending each item in the list as a separate message
                        "body": "{{ flow_context.results_display_parts }}"
                    }
                },
                "transitions": [
                    {"to_step": "ask_next_action_after_results", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "no_results_found",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "Sorry, no recent match results were found from the last 2 days. Please check back later."}
                },
                "transitions": [
                    {"to_step": "ask_next_action_after_results", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "ask_next_action_after_results",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": "What would you like to do next?"},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "results_start_betting", "title": "Start Betting"}},
                                    {"type": "reply", "reply": {"id": "results_main_menu", "title": "Main Menu"}}
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "results_next_action",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "switch_to_betting_from_results", "condition_config": {"type": "interactive_reply_id_equals", "value": "results_start_betting"}},
                    {"to_step": "switch_to_main_menu_from_results", "condition_config": {"type": "interactive_reply_id_equals", "value": "results_main_menu"}}
                ]
            },
            {
                "name": "switch_to_betting_from_results",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "bet"}]
                },
                "transitions": []
            },
            {
                "name": "switch_to_main_menu_from_results",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "menu"}]
                },
                "transitions": []
            }
        ]
    }