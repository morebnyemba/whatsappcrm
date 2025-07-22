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
                        "body": "Share your referral code with friends! When they sign up and make their first deposit, you both get a bonus!\n\nYour code: *{{ flow_context.referral_code }}*\n\nShare this message:\nHey! I'm using this awesome WhatsApp betting app. Sign up with my code *{{ flow_context.referral_code }}* and we both get a bonus! 🎉"
                    }
                },
                "transitions": [{"to_step": "end_referral_flow", "condition_config": {"type": "always_true"}}]
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