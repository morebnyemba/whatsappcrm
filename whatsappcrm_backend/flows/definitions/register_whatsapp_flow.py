# whatsappcrm_backend/flows/definitions/register_whatsapp_flow.py

"""
WhatsApp UI Flow JSON definition for User Registration.

This is the interactive registration form presented natively in WhatsApp
via Meta's Flow JSON schema.  The backend data-exchange endpoint at
``/crm-api/meta/flow-endpoint/`` handles account creation.

Screens:
    1. REGISTER  – collects username, email, password, confirm password
    2. COMPLETE  – terminal screen confirming registration
"""

REGISTER_WHATSAPP_FLOW = {
    "version": "6.0",
    "screens": [
        {
            "id": "REGISTER",
            "title": "Create Account",
            "data": {
                "error_message": {
                    "type": "string",
                    "__example__": ""
                }
            },
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {
                        "type": "TextHeading",
                        "text": "Register"
                    },
                    {
                        "type": "TextBody",
                        "text": "Create your account to get started."
                    },
                    {
                        "type": "Form",
                        "name": "register_form",
                        "children": [
                            {
                                "type": "TextInput",
                                "name": "username",
                                "label": "Username",
                                "required": True,
                                "input-type": "text",
                                "helper-text": "Choose a unique username"
                            },
                            {
                                "type": "TextInput",
                                "name": "email",
                                "label": "Email Address",
                                "required": True,
                                "input-type": "email",
                                "helper-text": "Enter a valid email address"
                            },
                            {
                                "type": "TextInput",
                                "name": "password",
                                "label": "Password",
                                "required": True,
                                "input-type": "password",
                                "helper-text": "Minimum 8 characters"
                            },
                            {
                                "type": "TextInput",
                                "name": "confirm_password",
                                "label": "Confirm Password",
                                "required": True,
                                "input-type": "password",
                                "helper-text": "Re-enter your password"
                            },
                            {
                                "type": "Footer",
                                "label": "Register",
                                "on-click-action": {
                                    "name": "data_exchange",
                                    "payload": {
                                        "username": "${form.username}",
                                        "email": "${form.email}",
                                        "password": "${form.password}",
                                        "confirm_password": "${form.confirm_password}",
                                        "action": "register"
                                    }
                                }
                            }
                        ]
                    }
                ]
            }
        },
        {
            "id": "COMPLETE",
            "title": "Registration Complete",
            "terminal": True,
            "success": True,
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {
                        "type": "TextHeading",
                        "text": "Welcome!"
                    },
                    {
                        "type": "TextBody",
                        "text": "Your account has been created successfully. You can now use the 'Login' option to sign in."
                    },
                    {
                        "type": "Footer",
                        "label": "Done",
                        "on-click-action": {
                            "name": "complete",
                            "payload": {
                                "registered": "true"
                            }
                        }
                    }
                ]
            }
        }
    ]
}


REGISTER_WHATSAPP_FLOW_METADATA = {
    "name": "register_whatsapp",
    "friendly_name": "Registration (Interactive)",
    "description": "Interactive WhatsApp UI flow for new user registration",
    "is_active": True,
}
