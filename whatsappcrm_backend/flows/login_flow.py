# whatsappcrm_backend/flows/login_flow.py

from typing import Dict, Any


def create_login_flow() -> Dict[str, Any]:
    """
    Defines the login flow for session authentication using WhatsApp UI Flows.
    Starts with Login/Register buttons. When "Login" is selected, a WhatsApp
    UI Flow is launched that presents a native login form. The form data is
    exchanged with a backend endpoint for authentication.
    This flow does NOT require login itself (it IS the login mechanism).
    """
    return {
        "name": "Login Flow",
        "description": "Authenticates a contact using a WhatsApp UI Flow with a backend data exchange endpoint.",
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
                        "body": "\u2705 You are already logged in! Type 'menu' to see available options."
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
                        "to_step": "send_login_flow_ui",
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "login_btn_login"}
                    },
                    {
                        "to_step": "send_register_flow_ui",
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "login_btn_register"}
                    }
                ]
            },
            # 4. Send WhatsApp UI Flow for login
            #    Uses flow_action "navigate" with flow_action_payload to directly open
            #    the LOGIN screen.  The flow_token is set to the contact's whatsapp_id
            #    so the endpoint can identify which contact is authenticating.
            {
                "name": "send_login_flow_ui",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "flow",
                            "header": {"type": "text", "text": "Login"},
                            "body": {"text": "Tap the button below to enter your credentials securely."},
                            "footer": {"text": "Your credentials are sent securely."},
                            "action": {
                                "name": "flow",
                                "parameters": {
                                    "flow_message_version": "3",
                                    "flow_action": "navigate",
                                    "flow_action_payload": {"screen": "LOGIN"},
                                    "flow_token": "{{ contact.whatsapp_id }}",
                                    "flow_id": "{{ flow_context.whatsapp_login_flow_id }}",
                                    "flow_cta": "Login"
                                }
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "login_nfm_response",
                        "expected_type": "any"
                    }
                },
                "transitions": [
                    {
                        "to_step": "process_flow_auth_result",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 5. Send WhatsApp UI Flow for registration
            #    Uses flow_action "navigate" with flow_action_payload to directly open
            #    the REGISTER screen.  The flow_token is set to the contact's whatsapp_id.
            {
                "name": "send_register_flow_ui",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "flow",
                            "header": {"type": "text", "text": "Register"},
                            "body": {"text": "Tap the button below to create your account."},
                            "footer": {"text": "Your information is sent securely."},
                            "action": {
                                "name": "flow",
                                "parameters": {
                                    "flow_message_version": "3",
                                    "flow_action": "navigate",
                                    "flow_action_payload": {"screen": "REGISTER"},
                                    "flow_token": "{{ contact.whatsapp_id }}",
                                    "flow_id": "{{ flow_context.whatsapp_register_flow_id }}",
                                    "flow_cta": "Register"
                                }
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "register_nfm_response",
                        "expected_type": "any"
                    }
                },
                "transitions": [
                    {
                        "to_step": "process_flow_register_result",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # 6. Process the Flow auth result (login path)
            #    After the WhatsApp Login Flow completes, the backend endpoint has
            #    already authenticated the user and started a ContactSession.
            #    We use check_session to verify the session was created successfully.
            {
                "name": "process_flow_auth_result",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "check_session",
                            "output_variable_name": "auth_result"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "login_success",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_equals",
                            "variable_name": "flow_context.auth_result",
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
            # 7. Process the Flow register result (register path)
            {
                "name": "process_flow_register_result",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "check_session",
                            "output_variable_name": "register_result"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "register_success",
                        "priority": 1,
                        "condition_config": {
                            "type": "variable_equals",
                            "variable_name": "flow_context.register_result",
                            "value": True
                        }
                    },
                    {
                        "to_step": "register_failed",
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
                        "body": "\u2705 Login successful! Your session is now active.\n\nType 'menu' to see available options."
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
                        "body": "\u274c Login was not completed. Please type 'login' to try again."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 10. Register success
            {
                "name": "register_success",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "\u2705 Registration successful! Your account has been created.\n\nType 'login' to sign in."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 11. Register failed
            {
                "name": "register_failed",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "\u274c Registration was not completed. Please type 'register' to try again."
                    }
                },
                "transitions": [
                    {"to_step": "end_login_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            # 12. End flow
            {
                "name": "end_login_flow",
                "step_type": "end_flow",
                "config": {}
            }
        ]
    }
