# whatsappcrm_backend/referrals/flows.py

def create_referral_flow():
    """
    Defines the flow for a user to get their referral code.
    This now points to the user's referral_profile.
    """
    return {
        "name": "Refer a Friend",
        "description": "Allows an existing user to get their referral code and a shareable message.",
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
                        "to_step": "generate_code",
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