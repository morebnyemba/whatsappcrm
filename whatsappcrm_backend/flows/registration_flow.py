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
                            "variable_name": "customer_profile.email"
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
                        "save_to_variable": "provided_email",
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
                            "action_type": "update_customer_profile",
                            "fields_to_update": {
                                "email": "{{ flow_context.provided_email }}"
                            }
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "create_account_step",
                        "priority": 1,
                        "condition_config": { # If email is the only thing needed, go straight to create_account
                            "type": "variable_exists",
                            "variable_name": "customer_profile.first_name" # Check if first_name already exists
                        }
                    },
                    {
                        "to_step": "ask_for_first_name",
                        "priority": 2,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 4. Ask for First Name
            {
                "name": "ask_for_first_name",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "What is your first name?"
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "provided_first_name",
                        "expected_type": "text"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Please provide a valid first name.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "We couldn't get your first name. Please type 'register' to try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "save_first_name_step",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 5. Save First Name
            {
                "name": "save_first_name_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "update_customer_profile",
                            "fields_to_update": {
                                "first_name": "{{ flow_context.provided_first_name }}"
                            }
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "ask_for_last_name",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 6. Ask for Last Name
            {
                "name": "ask_for_last_name",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "What is your last name?"
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "provided_last_name",
                        "expected_type": "text"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Please provide a valid last name.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "We couldn't get your last name. Please type 'register' to try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "save_last_name_step",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 7. Save Last Name
            {
                "name": "save_last_name_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "update_customer_profile",
                            "fields_to_update": {
                                "last_name": "{{ flow_context.provided_last_name }}"
                            }
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "ask_for_gender",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 8. Ask for Gender
            {
                "name": "ask_for_gender",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button", # Max 3 buttons
                            "body": {"text": "What is your gender? (Select one)"},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "gender_male", "title": "Male"}},
                                    {"type": "reply", "reply": {"id": "gender_female", "title": "Female"}},
                                    {"type": "reply", "reply": {"id": "gender_other", "title": "Other"}}
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "provided_gender_id", # Removed "flow_context." prefix
                        "expected_type": "interactive_id"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Please select one of the options for your gender.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "We couldn't get your gender. Please type 'register' to try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "save_gender_step",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 9. Save Gender
            {
                "name": "save_gender_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "update_customer_profile",
                            "fields_to_update": {
                                "gender": "{{ flow_context.provided_gender_id }}"
                            }
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "ask_for_dob",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 4. Create the account (convergence point)
            # 10. Ask for Date of Birth
            {
                "name": "ask_for_dob",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "What is your date of birth? (YYYY-MM-DD, e.g., 1990-01-15)"
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "provided_dob", # Removed "flow_context." prefix
                        "expected_type": "text",
                        "validation_regex": r"^\d{4}-\d{2}-\d{2}$" # Basic YYYY-MM-DD regex
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "That doesn't look like a valid date format (YYYY-MM-DD). Please try again.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "We couldn't validate your date of birth. Please type 'register' to try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "save_dob_step",
                        "priority": 1,
                        "condition_config": {
                            "type": "always_true"
                        }
                    }
                ]
            },
            # 11. Save Date of Birth
            {
                "name": "save_dob_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "update_customer_profile",
                            "fields_to_update": {
                                "date_of_birth": "{{ flow_context.provided_dob }}"
                            }
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "create_account_step",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 12. Create the account (convergence point)
            {
                "name": "create_account_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "create_account",
                            "email_template": "{{ flow_context.provided_email }}",
                            "first_name_template": "{{ flow_context.provided_first_name }}",
                            "last_name_template": "{{ flow_context.provided_last_name }}"
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
            # 13. Success message
            {
                "name": "registration_success",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "✅ Registration successful! Your account and wallet have been created.\n\n*Username:* {{ flow_context.user_username }}\n*Password:* {{ flow_context.generated_password }}\n\n_Please save these details securely. You can now start betting. Type 'menu' to see options._"
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
            # 14. Already registered message
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
            # 15. End flow
            {
                "name": "end_flow_after_registration",
                "step_type": "end_flow",
                "config": {}
            }
        ]
    }