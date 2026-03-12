# whatsappcrm_backend/referrals/flows.py

def create_referral_flow():
    """
    Defines the flow for the agent program.
    Only admin-designated agents (is_agent=True on their ReferralProfile) can
    access options. Regular users without agent status are directed to contact
    support. The flow never prompts users to register/sign up.
    """
    return {
        "name": "Agent Program",
        "description": "Interactive menu for agents to get their code, check referrals, and view earnings.",
        "trigger_keywords": ["refer", "refer a friend", "referral", "agent", "agent program"],
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
                            "value_template": "{{ customer_profile.user.id }}"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "check_if_user_is_agent",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "flow_context.has_account"
                        }
                    },
                    {
                        "to_step": "not_logged_in_message",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "check_if_user_is_agent",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "set_context_variable",
                            "variable_name": "is_agent",
                            "value_template": "{{ customer_profile.user.referral_profile.is_agent }}"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "show_agent_options",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_equals",
                            "variable_name": "flow_context.is_agent",
                            "value": True
                        }
                    },
                    {
                        "to_step": "not_an_agent_message",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "show_agent_options",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": "Welcome to the Agent Program! 🤝\nEarn commission when users you refer lose bets.\n\nWhat would you like to do?"},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "get_referral_code", "title": "Get My Agent Code"}},
                                    {"type": "reply", "reply": {"id": "check_agent_earnings", "title": "My Earnings"}},
                                    {"type": "reply", "reply": {"id": "check_total_referrals", "title": "My Referrals"}}
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
                    {"to_step": "get_agent_earnings", "condition_config": {"type": "interactive_reply_id_equals", "value": "check_agent_earnings"}},
                    {"to_step": "get_total_referrals", "condition_config": {"type": "interactive_reply_id_equals", "value": "check_total_referrals"}}
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
                "transitions": [{"to_step": "fetch_referral_settings_for_message", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "fetch_referral_settings_for_message",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "get_referral_settings",
                            "output_variable_name": "referral_settings"
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
                        "body": "Your personal agent code is here! 🚀\n\nCode: *{{ flow_context.referral_code }}*\n\nShare this code with your friends. When they register and place bets, you'll earn a *{{ flow_context.referral_settings.agent_commission_display }}* commission on every bet they lose! 💰\n\nI'll send the shareable message next. Just forward it to your friends!"
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
                        "body": "Hey! 🌟 I'm inviting you to join BetBlitz, the best betting platform on WhatsApp!\n\nUse my agent code when you sign up and we'll both get a bonus on your first deposit! 💰\n\nMy code: *{{ flow_context.referral_code }}*\n\nClick the link below to register with my code automatically:\nhttps://wa.me/263780784537?text=Hi!%20I'd%20like%20to%20register%20with%20agent%20code:%20{{ flow_context.referral_code }}\n\nLet's win together! 🏆"
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
                "name": "get_agent_earnings",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "get_agent_earnings",
                            "output_variable_name": "agent_earnings_data"
                        }
                    ]
                },
                "transitions": [{"to_step": "send_agent_earnings_message", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "send_agent_earnings_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "💰 *Agent Earnings Summary*\n\nTotal Earnings: *${{ flow_context.agent_earnings_data.total_earnings }}*\nTotal Referrals: *{{ flow_context.agent_earnings_data.total_referrals }}*\nCommission Rate: *{{ flow_context.agent_earnings_data.commission_display }}*\n\nKeep sharing your code to earn more! 🚀"
                    }
                },
                "transitions": [{"to_step": "ask_next_action_after_referral", "condition_config": {"type": "always_true"}}]
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
                        "body": "You have a total of *{{ flow_context.total_referrals_count }}* referred user(s). Keep up the great work! 🚀"
                    }
                },
                "transitions": [{"to_step": "ask_next_action_after_referral", "condition_config": {"type": "always_true"}}]
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
                "name": "not_logged_in_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "Please log in first to access the Agent Program. Type 'login' to sign in."}
                },
                "transitions": [{"to_step": "end_referral_flow", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "not_an_agent_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "You are not currently enrolled as an agent. Please contact support to be designated as an agent."}
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