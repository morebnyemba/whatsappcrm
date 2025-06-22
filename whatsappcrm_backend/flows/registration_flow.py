from typing import Dict, Any

def create_registration_flow() -> Dict[str, Any]:
    """
    Defines the structure for the user registration flow.
    This flow handles new user registration, creating a customer profile,
    a user account, and a wallet. It also informs users if they are already registered.
    It will ask for an email if one is not already on file.
    """
    return {
        "name": "User Registration",
        "description": "A flow to register new users, creating their profile and wallet.",
        "trigger_keywords": ["register", "join", "signup"],
        "is_active": True,
        "steps": [
            # 1. Entry point, immediately checks for email
            {
                "name": "start_registration",
                "step_type": "action", # Use action step for conditional transitions without user interaction
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [] # No actions, just for transitions
                },
                "transitions": [
                    {
                        "to_step": "create_account_step",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "contact.email"
                        }
                    },
                    {
                        "to_step": "ask_for_email",
                        "priority": 2,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 2. Ask for email if not present
            {
                "name": "ask_for_email",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "To complete your registration, please provide your email address."
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "flow_context.provided_email",
                        "expected_type": "email"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "That doesn't look like a valid email address. Please try again.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "We couldn't validate your email. Please type 'register' to try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "save_email_step",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true" # Transition after a valid reply is received
                        }
                    }
                ]
            },
            # 3. Save the provided email to the contact
            {
                "name": "save_email_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "update_contact_field",
                            "field_path": "email",
                            "value_template": "{{ flow_context.provided_email }}"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "create_account_step",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 4. Create the account (convergence point)
            {
                "name": "create_account_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "create_account",
                            "first_name_template": "{{ contact.name }}",
                            "email_template": "{{ contact.email }}"
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
            # 5. Success message
            {
                "name": "registration_success",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "✅ Registration successful! Your account and wallet have been created.\n\n*Username:* {{ flow_context.user.username }}\n*Password:* {{ flow_context.generated_password }}\n\n_Please save these details securely. You can now start betting. Type 'menu' to see options._"
                    }
                },
                "transitions": [
                    {
                        "to_step": "end_flow_after_registration",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 6. Already registered message
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
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 7. End flow
            {
                "name": "end_flow_after_registration",
                "step_type": "end_flow",
                "config": {}
            }
        ]
    }