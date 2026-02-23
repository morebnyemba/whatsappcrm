# whatsappcrm_backend/flows/login_flow.py

from typing import Dict, Any


def create_login_flow() -> Dict[str, Any]:
    """
    Defines the login flow for session authentication.
    Contacts are asked for their password/PIN to start an authenticated session.
    This flow does NOT require login itself (it IS the login mechanism).
    """
    return {
        "name": "Login Flow",
        "description": "Authenticates a contact by verifying their password/PIN to start a session.",
        "trigger_keywords": ["login", "signin"],
        "is_active": True,
        "requires_login": False,
        "steps": [
            # 1. Entry point - check if already authenticated
            {
                "name": "check_existing_session",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "check_session",
                            "output_variable_name": "session_valid"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "already_logged_in",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_equals",
                            "variable_name": "flow_context.session_valid",
                            "value": True
                        }
                    },
                    {
                        "to_step": "check_has_account",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 2. Already logged in
            {
                "name": "already_logged_in",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "✅ You are already logged in! Type 'menu' to see available options."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 3. Check if contact has an account
            {
                "name": "check_has_account",
                "step_type": "action",
                "config": {
                    "actions_to_run": []
                },
                "transitions": [
                    {
                        "to_step": "ask_for_pin",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_exists",
                            "variable_name": "customer_profile.user"
                        }
                    },
                    {
                        "to_step": "no_account_found",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 4. No account found
            {
                "name": "no_account_found",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "You don't have an account yet. Please type 'register' to create one first."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 5. Ask for PIN/password
            {
                "name": "ask_for_pin",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "🔒 Please enter your password to login:"
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "provided_pin",
                        "expected_type": "text"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Invalid password. Please try again.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "Too many failed attempts. Please try again later by typing 'login'."
                    }
                },
                "transitions": [
                    {
                        "to_step": "verify_pin_step",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 6. Verify PIN
            {
                "name": "verify_pin_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "verify_pin",
                            "pin_variable": "flow_context.provided_pin",
                            "output_variable_name": "pin_verified"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "login_success",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_equals",
                            "variable_name": "flow_context.pin_verified",
                            "value": True
                        }
                    },
                    {
                        "to_step": "login_failed",
                        "priority": 2,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 7. Login success
            {
                "name": "login_success",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "✅ Login successful! Your session is now active.\n\nType 'menu' to see available options."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 8. Login failed
            {
                "name": "login_failed",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "❌ Incorrect password. Please type 'login' to try again."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 9. End flow
            {
                "name": "end_login_flow",
                "step_type": "end_flow",
                "config": {}
            }
        ]
    }
