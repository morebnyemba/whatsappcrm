# whatsappcrm_backend/flows/get_fixtures_flow.py

def create_get_fixtures_flow():
    """
    Defines a simplified flow to show all upcoming matches without asking for a league.
    """
    return {
        "name": "View Football Fixtures", # Keep the name to update the existing flow
        "description": "Shows all upcoming football fixtures and prompts for next action.",
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
                            "days_ahead_for_fixtures": 10
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "send_all_fixtures",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "flow_context.pdf_url"
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
                    "message_type": "document",
                    "document": {
                        "link": "{{ flow_context.pdf_url }}",
                        "filename": "{{ flow_context.pdf_filename }}",
                        "caption": "⚽ Here are the upcoming football fixtures with odds. Tap to view the PDF."
                    }
                },
                "transitions": [
                    {"to_step": "ask_next_action_after_fixtures", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "no_fixtures_found",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "Sorry, no upcoming matches were found for the next 10 days. Please check back later."}
                },
                "transitions": [
                    {"to_step": "ask_next_action_after_fixtures", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "ask_next_action_after_fixtures",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": "What would you like to do next?"},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "fixtures_start_betting", "title": "Start Betting"}},
                                    {"type": "reply", "reply": {"id": "fixtures_main_menu", "title": "Main Menu"}}
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "fixtures_next_action",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "switch_to_betting", "condition_config": {"type": "interactive_reply_id_equals", "value": "fixtures_start_betting"}},
                    {"to_step": "switch_to_main_menu", "condition_config": {"type": "interactive_reply_id_equals", "value": "fixtures_main_menu"}}
                ]
            },
            {
                "name": "switch_to_betting",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "bet"}]
                },
                "transitions": []
            },
            {
                "name": "switch_to_main_menu",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "menu"}]
                },
                "transitions": []
            },
            {
                "name": "end_fixtures_flow",
                "step_type": "end_flow",
                "config": {},
                "transitions": []
            }
        ]
    }
