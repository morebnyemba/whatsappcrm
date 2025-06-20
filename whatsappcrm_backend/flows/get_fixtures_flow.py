# whatsappcrm_backend/flows/get_fixtures_flow.py

from typing import Dict, Any, List
from football_data_app.models import League # Import the League model

# --- Constants for Reply IDs ---
REPLY_ID_VIEW_ANOTHER_LEAGUE = "fixtures_view_another_league"
REPLY_ID_MAIN_MENU_FROM_FIXTURES = "fixtures_go_to_main_menu"

def create_get_fixtures_flow() -> Dict[str, Any]:
    """
    Defines the structure for the "View Football Fixtures" flow
    using interactive messages for league selection.
    """
    flow_name = "View Football Fixtures"
    flow_description = "Allows users to view upcoming football fixtures by league using interactive messages."
    flow_trigger_keywords = ["fixtures", "view matches", "upcoming games", "view fixtures"]

    # --- Step Names ---
    STEP_0_NO_LEAGUES = "Fixtures - No Leagues Available"
    STEP_1_ASK_LEAGUE = "Fixtures - Ask League"
    STEP_2_FETCH_FIXTURES = "Fixtures - Fetch Fixtures"
    STEP_3_SEND_FIXTURES_LIST = "Fixtures - Send Fixtures List"
    STEP_4_NO_FIXTURES_FOR_LEAGUE = "Fixtures - No Fixtures for Selected League"
    STEP_5_MORE_OPTIONS = "Fixtures - More Options After Fixtures"
    STEP_6_GO_TO_MAIN_MENU = "Fixtures - Go to Main Menu Action"
    STEP_END_FLOW_GENERIC = "Fixtures - End Flow (Generic)"

    steps_definitions = []
    
    # Dynamically fetch active leagues to build the interactive list.
    # This code runs when create_get_fixtures_flow() is called (e.g., during seeding by create_flow.py).
    # We'll take up to 10 active leagues for a single interactive list section.
    active_leagues = list(League.objects.filter(active=True).order_by('name')[:10])

    is_entry_point_ask_league = bool(active_leagues)
    is_entry_point_no_leagues = not active_leagues

    # Step 0: No Leagues Available (Conditional Entry Point)
    if not active_leagues:
        steps_definitions.append({
            "name": STEP_0_NO_LEAGUES,
            "step_type": "send_message", # Sends a message and then transitions
            "is_entry_point": is_entry_point_no_leagues,
            "config": {
                "message_type": "text",
                "text": {"body": "Sorry, there are currently no football leagues available to display fixtures for. Please check back later."}
            },
            "transitions": [
                {"to_step": STEP_END_FLOW_GENERIC, "condition_config": {"type": "always_true"}}
            ]
        })

    # Step 1: Ask League (Conditional Entry Point if leagues exist)
    if active_leagues:
        league_rows_for_interactive_list = []
        for league in active_leagues:
            league_rows_for_interactive_list.append({
                "id": str(league.api_id), # Use the actual api_id as the interactive reply ID
                "title": league.name[:24], # WhatsApp List Row Title: Max 24 chars
                "description": (league.short_name or league.name)[:72] # WhatsApp List Row Description: Max 72 chars
            })

        steps_definitions.append({
            "name": STEP_1_ASK_LEAGUE,
            "step_type": "question",
            "is_entry_point": is_entry_point_ask_league,
            "config": {
                "message_config": {
                    "message_type": "interactive",
                    "interactive": {
                        "type": "list",
                        "header": {"type": "text", "text": "Leagues"}, # Max 60 chars
                        "body": {"text": "Please select a football league to view fixtures:"}, # Max 1024 chars
                        "footer": {"text": "Tap to choose"}, # Max 60 chars
                        "action": {
                            "button": "View Leagues", # Max 20 chars
                            "sections": [{"title": "Available Leagues", "rows": league_rows_for_interactive_list}] # Max 10 rows per section
                        }
                    }
                },
                "reply_config": {
                    "save_to_variable": "selected_league_api_id", # Saves to flow_context.selected_league_api_id
                    "expected_type": "interactive_id" 
                },
                "fallback_config": { 
                    "re_prompt_message_text": "Please select a league from the list provided.",
                    "max_retries": 1,
                    "action_after_max_retries": "end_flow", 
                    "end_flow_message_text": "Okay, let's try that another time. You can say 'menu' to see other options."
                }
            },
            "transitions": [
                {
                    "to_step": STEP_2_FETCH_FIXTURES,
                    "condition_config": {"type": "question_reply_is_valid", "value": True} 
                }
                # Fallback transition (if reply invalid after retries) is handled by fallback_config's action_after_max_retries
            ]
        })

    # Step 2: Fetch Fixtures (Action Step)
    steps_definitions.append({
        "name": STEP_2_FETCH_FIXTURES,
        "step_type": "action",
        "config": {
            "actions_to_run": [
                {
                    "action_type": "fetch_football_data",
                    "data_type": "scheduled_fixtures",
                    "league_code_variable": "selected_league_api_id", # Variable name in flow_context
                    "output_variable_name": "fixtures_display_parts", # Saves to flow_context.fixtures_display_parts
                    "days_ahead_for_fixtures": 7 
                }
            ]
        },
        "transitions": [
            {
                "to_step": STEP_3_SEND_FIXTURES_LIST,
                "condition_config": {
                    "type": "variable_exists", 
                    "variable_name": "flow_context.fixtures_display_parts" # Checks if not None
                },
                "priority": 1 
            },
            {
                "to_step": STEP_4_NO_FIXTURES_FOR_LEAGUE,
                "condition_config": {"type": "always_true"}, 
                "priority": 2 
            }
        ]
    })

    # Step 3: Send Fixtures List (Send Message Step)
    steps_definitions.append({
        "name": STEP_3_SEND_FIXTURES_LIST,
        "step_type": "send_message",
        "config": {
            "message_type": "text",
            "text": {
                # services.py handles sending each item in the list as a separate message
                "body": "{{ flow_context.fixtures_display_parts }}" 
            }
        },
        "transitions": [
            {"to_step": STEP_5_MORE_OPTIONS, "condition_config": {"type": "always_true"}}
        ]
    })

    # Step 4: No Fixtures for Selected League (Send Message Step)
    steps_definitions.append({
        "name": STEP_4_NO_FIXTURES_FOR_LEAGUE,
        "step_type": "send_message",
        "config": {
            "message_type": "text",
            "text": {"body": "Sorry, no upcoming fixtures were found for the selected league or the specified period."}
        },
        "transitions": [
            {"to_step": STEP_5_MORE_OPTIONS, "condition_config": {"type": "always_true"}}
        ]
    })

    # Step 5: More Options (Question Step with Interactive Buttons)
    steps_definitions.append({
        "name": STEP_5_MORE_OPTIONS,
        "step_type": "question",
        "config": {
            "message_config": {
                "message_type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": "What would you like to do next?"},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": REPLY_ID_VIEW_ANOTHER_LEAGUE, "title": "Other Leagues"}},
                            {"type": "reply", "reply": {"id": REPLY_ID_MAIN_MENU_FROM_FIXTURES, "title": "Main Menu"}}
                        ]
                    }
                }
            },
            "reply_config": {
                "save_to_variable": "fixtures_next_action_choice", # Saves to flow_context.fixtures_next_action_choice
                "expected_type": "interactive_id"
            },
            "fallback_config": {
                "re_prompt_message_text": "Please use the buttons to make a selection.",
                "max_retries": 1,
                "action_after_max_retries": "end_flow", 
                "end_flow_message_text": "Okay, ending this session. Type 'menu' for main options."
            }
        },
        "transitions": [
            {
                "to_step": STEP_1_ASK_LEAGUE, # Go back to league selection
                "condition_config": {
                    "type": "variable_equals",
                    "variable_name": "flow_context.fixtures_next_action_choice",
                    "value": REPLY_ID_VIEW_ANOTHER_LEAGUE
                },
                "priority": 1
            },
            {
                "to_step": STEP_6_GO_TO_MAIN_MENU,
                "condition_config": {
                    "type": "variable_equals",
                    "variable_name": "flow_context.fixtures_next_action_choice",
                    "value": REPLY_ID_MAIN_MENU_FROM_FIXTURES
                },
                "priority": 2
            }
        ]
    })

    # Step 6: Go to Main Menu (Action Step)
    steps_definitions.append({
        "name": STEP_6_GO_TO_MAIN_MENU,
        "step_type": "action",
        "config": {
            "actions_to_run": [
                {
                    "action_type": "switch_flow",
                    "target_flow_name": "Main Menu", # IMPORTANT: Ensure a flow named "Main Menu" exists
                }
            ]
        },
        "transitions": [
            # switch_flow action should implicitly end the current flow's processing.
            # If an explicit end is desired after the switch action (though usually not needed):
            {"to_step": STEP_END_FLOW_GENERIC, "condition_config": {"type": "always_true"}}
        ]
    })

    # Step End Flow: Common end point for flows that don't switch
    steps_definitions.append({
        "name": STEP_END_FLOW_GENERIC,
        "step_type": "end_flow",
        "config": {
            # Optional: send a final message before ending if not handled by fallback_config
            # "message_config": {
            #     "message_type": "text",
            #     "text": {"body": "Thank you for using the fixtures service!"}
            # }
        },
        "transitions": [] # No transitions from an end_flow step
    })

    return {
        "name": flow_name,
        "description": flow_description,
        "trigger_keywords": flow_trigger_keywords,
        "steps": steps_definitions
    }
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "fetch_football_data",
                            "data_type": "scheduled_fixtures",
                            "output_variable_name": "fixtures_display_parts"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "Send Fixtures List", # Transition to the new, simplified step
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "flow_context.fixtures_display_parts"
                        }
                    },
                    {
                        "to_step": "Send No Fixtures Message",
                        "condition_config": { "type": "always_true" }
                    }
                ]
            },
            {
                "name": "Send Fixtures List",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    # This is the key change. We pass the entire list to the body.
                    # Your services.py will automatically handle sending each item.
                    "text": {
                        "body": "{{ flow_context.fixtures_display_parts }}"
                    }
                },
                "transitions": [
                    {
                        "to_step": "end_flow",
                        "condition_config": { "type": "always_true" }
                    }
                ]
            },
            {
                "name": "Send No Fixtures Message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": { "body": "Sorry, no upcoming fixtures were found." }
                },
                "transitions": [
                    {
                        "to_step": "end_flow",
                        "condition_config": { "type": "always_true" }
                    }
                ]
            },
            {
                "name": "end_flow",
                "step_type": "end_flow",
                "config": {},
                "transitions": []
            }
        ]
    }
