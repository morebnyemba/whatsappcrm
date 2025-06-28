# whatsappcrm_backend/flows/betting_flow.py

def create_betting_flow():
    """
    Defines a flow for handling sports betting activities.
    """
    return {
        "name": "Betting Flow",
        "description": "Guides the user through viewing matches, placing bets, and checking tickets.",
        "trigger_keywords": ["bet", "play", "ticket", "matches", "odds"],
        "is_active": True,
        "steps": [
            # 1. Entry Point: Ensure user has an account
            {
                "name": "ensure_customer_account_betting",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [{"action_type": "create_account"}]
                },
                "transitions": [
                    {"to_step": "show_betting_menu", "priority": 1, "condition_config": {"type": "variable_equals", "variable_name": "account_creation_status", "value": True}},
                    {"to_step": "account_creation_failed_betting", "priority": 99, "condition_config": {"type": "always_true"}}
                ]
            },
            # 2. Main Menu
            {
                "name": "show_betting_menu",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "list",
                            "header": {"type": "text", "text": "Betting Menu"},
                            "body": {"text": "Welcome to BetBlitz! What would you like to do?"},
                            "footer": {"text": "Select an option"},
                            "action": {
                                "button": "Menu",
                                "sections": [
                                    {
                                        "title": "Betting Options",
                                        "rows": [
                                            {"id": "bet_view_matches", "title": "View Matches & Odds", "description": "See upcoming matches and their odds"},
                                            {"id": "bet_view_results", "title": "View Results", "description": "See results for finished matches"},
                                            {"id": "bet_place_text", "title": "Place Bet (Text)", "description": "Place a bet using text commands"},
                                            {"id": "bet_view_single_ticket", "title": "View Ticket by ID", "description": "View details of a specific ticket"},
                                            {"id": "bet_check_balance", "title": "Check Balance", "description": "View your current wallet balance"},
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "selected_betting_option",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "switch_to_get_fixtures", "condition_config": {"type": "interactive_reply_id_equals", "value": "bet_view_matches"}},
                    {"to_step": "ask_league_for_results", "condition_config": {"type": "interactive_reply_id_equals", "value": "bet_view_results"}},
                    {"to_step": "ask_for_bet_string", "condition_config": {"type": "interactive_reply_id_equals", "value": "bet_place_text"}},
                    {"to_step": "ask_for_ticket_id", "condition_config": {"type": "interactive_reply_id_equals", "value": "bet_view_single_ticket"}},
                    {"to_step": "fetch_wallet_balance", "condition_config": {"type": "interactive_reply_id_equals", "value": "bet_check_balance"}},
                ]
            },
            # --- Switch to Get Fixtures Flow ---
            {
                "name": "switch_to_get_fixtures",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "fixtures"}]
                },
                "transitions": []
            },
            # --- Path 1: View Results ---
            {
                "name": "ask_league_for_results",
                "step_type": "question",
                "config": {
                    "message_config": {"message_type": "text", "text": {"body": "Enter a league code (e.g., 'epl', 'laliga') or type 'all' to see recent results from all available leagues."}},
                    "reply_config": {"save_to_variable": "selected_league_code", "expected_type": "text"}
                },
                "transitions": [
                    {"to_step": "fetch_results", "condition_config": {"type": "question_reply_is_valid", "value": True}}
                ]
            },
            {
                "name": "fetch_results",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{
                        "action_type": "handle_betting_action",
                        "betting_action": "view_results",
                        "league_code_template": "{{ flow_context.selected_league_code }}"
                    }]
                },
                "transitions": [
                    {"to_step": "display_results", "condition_config": {"type": "variable_equals", "variable_name": "view_results_status", "value": True}},
                    {"to_step": "betting_action_failed", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "display_results",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "{{ flow_context.view_results_message }}"}
                },
                "transitions": [
                    {"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # --- Path 3: View Single Ticket by ID ---
            {
                "name": "ask_for_ticket_id",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter the ID of the ticket you wish to view:"}
                    },
                    "reply_config": {"save_to_variable": "ticket_id_for_lookup", "expected_type": "number"}
                },
                "transitions": [
                    {"to_step": "fetch_single_ticket_details", "condition_config": {"type": "question_reply_is_valid", "value": True}},
                    {"to_step": "betting_action_failed", "condition_config": {"type": "always_true"}} # Fallback for invalid input
                ]
            },
            {
                "name": "fetch_single_ticket_details",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{
                        "action_type": "handle_betting_action",
                        "betting_action": "view_single_ticket",
                        "ticket_id_template": "{{ flow_context.ticket_id_for_lookup }}"
                    }]
                },
                "transitions": [
                    {"to_step": "display_single_ticket_details", "priority": 1, "condition_config": {"type": "variable_equals", "variable_name": "single_ticket_status", "value": True}},
                    {"to_step": "single_ticket_not_found", "priority": 99, "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "display_single_ticket_details",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "{{ flow_context.single_ticket_message }}"}},
                "transitions": [{"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}]
            },
            # --- Path 2: Place Bet via Text ---
            {
                "name": "ask_for_bet_string",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter your bets, one per line, followed by your stake.\n\nExample:\n123 Home\n456 Over 2.5\nStake 10"}
                    },
                    "reply_config": {"save_to_variable": "raw_bet_string", "expected_type": "text"}
                },
                "transitions": [
                    {"to_step": "parse_bet_string_for_confirmation", "condition_config": {"type": "question_reply_is_valid", "value": True}}
                ]
            },
            {
                "name": "parse_bet_string_for_confirmation",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{
                        "action_type": "handle_betting_action",
                        "betting_action": "parse_and_confirm_ticket",
                        "raw_bet_string_template": "{{ flow_context.raw_bet_string }}"
                    }]
                },
                "transitions": [
                    {"to_step": "ask_for_bet_confirmation", "priority": 1, "condition_config": {"type": "variable_equals", "variable_name": "bet_parsing_status", "value": True}},
                    {"to_step": "bet_parsing_failed", "priority": 99, "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "ask_for_bet_confirmation",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button",
                            "header": {"type": "text", "text": "Confirm Your Bet"},
                            "body": {"text": "{{ flow_context.bet_confirmation_message }}"},
                            "footer": {"text": "Please confirm to proceed."},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "confirm_bet_yes", "title": "✅ Yes, Place Bet"}},
                                    {"type": "reply", "reply": {"id": "confirm_bet_no", "title": "❌ No, Cancel"}}
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "bet_confirmation_response",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "process_confirmed_bet", "condition_config": {"type": "interactive_reply_id_equals", "value": "confirm_bet_yes"}},
                    {"to_step": "bet_cancelled", "condition_config": {"type": "interactive_reply_id_equals", "value": "confirm_bet_no"}}
                ]
            },
            {
                "name": "process_confirmed_bet",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{
                        "action_type": "handle_betting_action",
                        "betting_action": "place_ticket_from_context"
                    }]
                },
                "transitions": [
                    {"to_step": "display_bet_placement_result", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "display_bet_placement_result",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "{{ flow_context.place_ticket_message }}"}
                },
                "transitions": [
                    {"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "bet_cancelled",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "Your bet has been cancelled as requested."}
                },
                "transitions": [{"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}]
            },
            # --- Path 3 & 4 are handled by handle_betting_action which sets a message in context ---
            {
                "name": "fetch_wallet_balance",
                "step_type": "action",
                "config": {"actions_to_run": [{"action_type": "handle_betting_action", "betting_action": "check_wallet_balance"}]},
                "transitions": [{"to_step": "display_betting_action_result", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "display_betting_action_result",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "{{ flow_context.view_my_tickets_message | default:'' }}{{ flow_context.check_wallet_balance_message | default:'' }}"}},
                "transitions": [{"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}]
            },
            # --- Common Failure/End Steps ---
            {
                "name": "account_creation_failed_betting",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "❌ We couldn't set up your account at this time. {{ flow_context.account_creation_message }}"}},
                "transitions": [{"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "bet_parsing_failed",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "❌ We couldn't understand your bet. {{ flow_context.bet_parsing_message | default:'Please check the format and try again.' }}"}},
                "transitions": [{"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "single_ticket_not_found",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "Ticket ID {{ flow_context.ticket_id_for_lookup }} not found or does not belong to you. Please check the ID and try again."}},
                "transitions": [{"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "betting_action_failed",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "❌ Sorry, something went wrong. {{ flow_context.view_results_message | default:flow_context.view_matches_message | default:'Please try again.' }}"}},
                "transitions": [{"to_step": "end_betting_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "end_betting_flow",
                "step_type": "end_flow",
                "config": {"message_config": {"message_type": "text", "text": {"body": "Thanks for using BetBlitz! Good luck!"}}}
            }
        ]
    }