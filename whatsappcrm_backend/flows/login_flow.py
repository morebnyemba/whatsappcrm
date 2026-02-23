# whatsappcrm_backend/flows/login_flow.py

from typing import Dict, Any


def create_login_flow() -> Dict[str, Any]:
    """
    Defines the login flow for session authentication.
    Starts with Login/Register buttons. Any contact can log in with any
    valid username and password.
    This flow does NOT require login itself (it IS the login mechanism).
    """
    return {
        "name": "Login Flow",
        "description": "Authenticates a contact by verifying their username and password to start a session.",
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
                        "to_step": "show_login_register_buttons",
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
            # 3. Show Login / Register buttons
            {
                "name": "show_login_register_buttons",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "button",
                            "body": {"text": "Welcome! Please choose an option below to continue."},
                            "action": {
                                "buttons": [
                                    {"type": "reply", "reply": {"id": "login_btn_login", "title": "Login"}},
                                    {"type": "reply", "reply": {"id": "login_btn_register", "title": "Register"}}
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "login_register_choice",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {
                        "to_step": "ask_for_username",
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "login_btn_login"}
                    },
                    {
                        "to_step": "switch_to_registration",
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "login_btn_register"}
                    }
                ]
            },
            # 4. Switch to registration flow
            {
                "name": "switch_to_registration",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {"action_type": "switch_flow", "trigger_keyword_template": "register"}
                    ]
                },
                "transitions": []
            },
            # 5. Ask for username
            {
                "name": "ask_for_username",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "Please enter your username:"
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "provided_username",
                        "expected_type": "text"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Please enter a valid username.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "Too many failed attempts. Please try again later by typing 'login'."
                    }
                },
                "transitions": [
                    {
                        "to_step": "ask_for_password",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 6. Ask for password
            {
                "name": "ask_for_password",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "🔒 Please enter your password:"
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
                        "to_step": "verify_credentials_step",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 7. Verify credentials (username + password)
            {
                "name": "verify_credentials_step",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "verify_pin",
                            "pin_variable": "flow_context.provided_pin",
                            "username_variable": "flow_context.provided_username",
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
            # 8. Login success
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
            # 9. Login failed
            {
                "name": "login_failed",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "❌ Incorrect username or password. Please type 'login' to try again."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 10. End flow
            {
                "name": "end_login_flow",
                "step_type": "end_flow",
                "config": {}
            }
        ]
    }
