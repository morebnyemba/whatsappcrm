# whatsappcrm_backend/referrals/flows.py

def create_referral_flow():
    """
    Defines the flow for a user to get their referral code.
    This is now an interactive menu for the referral program.
    """
    return {
        "name": "Refer a Friend",
        "description": "Interactive menu for users to get their referral code and check referral status.",
        "trigger_keywords": ["refer", "refer a friend", "referral"],
        "is_active": True,
        "steps": [
            {
                "name": "check_if_user_has_account",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "set_context_variable",
                            "variable_name": "has_account",
                            # Check for the user on the customer_profile
                            "value_template": "{{ customer_profile.user.id }}"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "show_referral_options",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "flow_context.has_account"
                        }
                    },
                    {
                        "to_step": "prompt_to_create_account",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "show_referral_options",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": "Welcome to the Referral Program! What would you like to do?"},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "get_referral_code", "title": "Get My Code"}},
                                    {"type": "reply", "reply": {"id": "check_total_referrals", "title": "Total Referrals"}},
                                    {"type": "reply", "reply": {"id": "check_pending_referrals", "title": "Pending Referrals"}}
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "referral_menu_choice",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "generate_code", "condition_config": {"type": "interactive_reply_id_equals", "value": "get_referral_code"}},
                    {"to_step": "get_total_referrals", "condition_config": {"type": "interactive_reply_id_equals", "value": "check_total_referrals"}},
                    {"to_step": "get_pending_referrals", "condition_config": {"type": "interactive_reply_id_equals", "value": "check_pending_referrals"}}
                ]
            },
            {
                "name": "generate_code",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "generate_referral_code",
                            "output_variable_name": "referral_code"
                        }
                    ]
                },
                "transitions": [{"to_step": "send_code_message", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "send_code_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "Your personal referral code is here! 🚀\n\nCode: *{{ flow_context.referral_code }}*\n\nShare this code with your friends. When they register and make their first deposit, you will *each* receive a bonus equal to 25% of their deposit amount! 💰\n\nI'll send the shareable message next. Just forward it to your friends!"
                    }
                },
                "transitions": [{"to_step": "send_shareable_referral_message", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "send_shareable_referral_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "Hey! 🌟 I'm inviting you to join BetBlitz, the best betting platform on WhatsApp!\n\nUse my referral code when you sign up, and we will *each* get a bonus equal to *25%* of your first deposit! 💰\n\nMy code: *{{ flow_context.referral_code }}*\n\nClick the link below to register with my code automatically:\nhttps://wa.me/263780784537?text=Hi!%20I'd%20like%20to%20register%20with%20referral%20code:%20{{ flow_context.referral_code }}\n\nLet's win together! 🏆"
                    }
                },
                "transitions": [{"to_step": "ask_next_action_after_referral", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "ask_next_action_after_referral",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": "What would you like to do next?"},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "referral_main_menu", "title": "Main Menu"}},
                                    {"type": "reply", "reply": {"id": "referral_done", "title": "I'm Done"}}
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "referral_next_action",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "switch_to_main_menu_from_referral", "condition_config": {"type": "interactive_reply_id_equals", "value": "referral_main_menu"}},
                    {"to_step": "end_referral_flow", "condition_config": {"type": "interactive_reply_id_equals", "value": "referral_done"}}
                ]
            },
            {
                "name": "get_total_referrals",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "get_total_referrals",
                            "output_variable_name": "total_referrals_count"
                        }
                    ]
                },
                "transitions": [{"to_step": "send_total_referrals_message", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "send_total_referrals_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "You have a total of *{{ flow_context.total_referrals_count }}* successful referral(s). Keep up the great work! 🚀"
                    }
                },
                "transitions": [{"to_step": "end_referral_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "get_pending_referrals",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "get_pending_referrals",
                            "output_variable_name": "pending_referrals_count"
                        }
                    ]
                },
                "transitions": [{"to_step": "send_pending_referrals_message", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "send_pending_referrals_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "You have *{{ flow_context.pending_referrals_count }}* pending referral(s). A referral becomes successful once your friend makes their first deposit."
                    }
                },
                "transitions": [{"to_step": "end_referral_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "switch_to_main_menu_from_referral",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "menu"}]
                },
                "transitions": []
            },
            {
                "name": "prompt_to_create_account",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "You need to have an account to refer friends. Type 'register' to create one!"}
                },
                "transitions": [{"to_step": "end_referral_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "end_referral_flow",
                "step_type": "end_flow",
                "config": {},
                "transitions": []
            }
        ]
    }