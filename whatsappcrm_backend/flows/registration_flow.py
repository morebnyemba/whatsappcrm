from typing import Dict, Any

def create_registration_flow() -> Dict[str, Any]:
    """
    Defines the structure for the user registration flow.
    This flow handles new user registration, creating a customer profile,
    a user account, and a wallet. It also informs users if they are already registered.
    """
    return {
        "name": "User Registration",
        "description": "A flow to register new users, creating their profile and wallet.",
        "trigger_keywords": ["register", "join", "signup"],
        "is_active": True,
        "steps": [
            {
                "name": "start_registration",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "create_account",
                            "first_name_template": "{{ contact.name }}"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "registration_success",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_equals",
                            "variable_name": "flow_context.user_created",
                            "value": True
                        }
                    },
                    {
                        "to_step": "already_registered",
                        "priority": 2,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            {
                "name": "registration_success",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "✅ Registration successful! Your account and wallet have been created. You can now start betting. Type 'menu' to see options."
                    },
                    # Could add more details here if needed
                },
                "transitions": [
                    {
                        "to_step": "end_flow_after_registration",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            {
                "name": "already_registered",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "Looks like you are already registered! 👍\nType 'menu' to see what you can do."
                    }
                },
                "transitions": [
                    {
                        "to_step": "end_flow_after_registration",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            {
                "name": "end_flow_after_registration",
                "step_type": "end_flow",
                "config": {}
            }
        ]
    }