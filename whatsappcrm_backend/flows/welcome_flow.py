# whatsappcrm_backend/flows/welcome_flow.py

def create_welcome_flow():
    """
    Defines the main welcome flow that acts as a central menu for the user.
    """
    return {
        "name": "Welcome Flow",
        "description": "The main entry point for users, providing a menu of options.",
        "trigger_keywords": ["hi", "hello", "menu", "start"],
        "is_active": True,
        "steps": [
            {
                "name": "show_welcome_menu",
                "step_type": "question",
                "is_entry_point": True,
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "list",
                            "header": {"type": "text", "text": "Welcome to BetBlitz"},
                            "body": {"text": "Your ultimate betting companion. Please select an option from the menu below to get started."},
                            "footer": {"text": "BetBlitz - Bet with Confidence"},
                            "action": {
                                "button": "Main Menu",
                                "sections": [
                                    {
                                        "title": "Services",
                                        "rows": [
                                            {"id": "welcome_register", "title": "Register (New Users)", "description": "Sign up for a new BetBlitz account"},
                                            {"id": "welcome_betting", "title": "Betting", "description": "Explore matches, odds, and place your bets"},
                                            {"id": "welcome_account", "title": "Account Management", "description": "Manage your funds, deposits, and withdrawals"},
                                            {"id": "welcome_agent_program", "title": "Agent Program", "description": "Earn commission when your referrals lose bets"},
                                        ]
                                    },
                                    {
                                        "title": "Information",
                                        "rows": [
                                            {"id": "welcome_about", "title": "About Us", "description": "Discover our mission and what we offer"},
                                            {"id": "welcome_support", "title": "Support", "description": "Find answers or connect with our support team"},
                                            {"id": "welcome_developer", "title": "Contact Developer", "description": "Information for technical inquiries or feedback"},
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "selected_welcome_option",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "switch_to_registration", "condition_config": {"type": "interactive_reply_id_equals", "value": "welcome_register"}},
                    {"to_step": "switch_to_betting", "condition_config": {"type": "interactive_reply_id_equals", "value": "welcome_betting"}},
                    {"to_step": "switch_to_account_management", "condition_config": {"type": "interactive_reply_id_equals", "value": "welcome_account"}},
                    {"to_step": "switch_to_agent_program", "condition_config": {"type": "interactive_reply_id_equals", "value": "welcome_agent_program"}},
                    {"to_step": "show_about_us", "condition_config": {"type": "interactive_reply_id_equals", "value": "welcome_about"}},
                    {"to_step": "show_support", "condition_config": {"type": "interactive_reply_id_equals", "value": "welcome_support"}},
                    {"to_step": "show_developer_contact", "condition_config": {"type": "interactive_reply_id_equals", "value": "welcome_developer"}},
                ]
            },
            # --- Switch Flow Actions ---
            {
                "name": "switch_to_registration",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "register"}]
                },
                "transitions": [] # No transitions, as the flow will be switched
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
                "name": "switch_to_account_management",
                "step_type": "action",
                "config": {"actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "account"}]},
                "transitions": []
            },
            {
                "name": "switch_to_agent_program",
                "step_type": "action",
                "config": {"actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "agent"}]},
                "transitions": []
            },
            # --- Simple Message Steps ---
            {
                "name": "show_about_us",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "BetBlitz is a premier WhatsApp-based betting platform, designed for ease of use and reliability. Happy betting!"}},
                "transitions": [{"to_step": "end_welcome_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "show_support",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "For support, please contact our helpdesk at support@betblitz.com or call +123456789."}},
                "transitions": [{"to_step": "end_welcome_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "show_developer_contact",
                "step_type": "send_message",
                "config": {
                    "message_type": "text", 
                    "text": {
                        "body": "This platform was developed by Moreblessing Nyemba from Slyker Tech Web Services.\n\n"
                                "You can reach them via:\n"
                                "- WhatsApp: https://wa.me/263787211325?text=Hello%20Slyker%20Tech\n"
                                "- Call: +263787211325\n"
                                "- Email: morebnyemba@slykertech.co.zw"
                    }
                },
                "transitions": [{"to_step": "end_welcome_flow", "condition_config": {"type": "always_true"}}]
            },
            # --- End Flow Step ---
            {
                "name": "end_welcome_flow",
                "step_type": "end_flow",
                "config": {} # No final message needed as the user is just sent back to the start
            }
        ]
    }