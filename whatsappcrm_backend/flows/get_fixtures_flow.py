# whatsappcrm_backend/flows/get_fixtures_flow.py

def create_get_fixtures_flow():
    """
    Defines a simplified flow to show all upcoming matches without asking for a league.
    """
    return {
        "name": "View Football Fixtures", # Keep the name to update the existing flow
        "description": "Shows all upcoming football fixtures from all available leagues.",
        "trigger_keywords": ["fixtures", "matches", "view matches", "upcoming games"],
        "is_active": True,
        "steps": [
            {
                "name": "fetch_all_fixtures",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "fetch_football_data",
                            "data_type": "scheduled_fixtures",
                            # No league_code_variable, so it fetches for all leagues
                            "output_variable_name": "fixtures_display_parts",
                            "days_ahead_for_fixtures": 7
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "send_all_fixtures",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "flow_context.fixtures_display_parts"
                        }
                    },
                    {
                        "to_step": "no_fixtures_found",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "send_all_fixtures",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        # The service layer will handle sending each item in the list as a separate message
                        "body": "{{ flow_context.fixtures_display_parts }}"
                    }
                },
                "transitions": [
                    {"to_step": "end_fixtures_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "no_fixtures_found",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "Sorry, no upcoming matches were found for the next 7 days. Please check back later."}
                },
                "transitions": [
                    {"to_step": "end_fixtures_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "end_fixtures_flow",
                "step_type": "end_flow",
                "config": {},
                "transitions": []
            }
        ]
    }
