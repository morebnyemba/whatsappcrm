# whatsappcrm_backend/flows/definitions/login_whatsapp_flow.py

"""
WhatsApp UI Flow JSON definition for Login.

This is the interactive login form presented natively in WhatsApp via
Meta's Flow JSON schema.  The backend data-exchange endpoint at
``/crm-api/meta/flow-endpoint/`` handles authentication.
"""

LOGIN_WHATSAPP_FLOW = {
    "version": "6.0",
    "data_api_version": "3.0",
    "screens": [
        {
            "id": "LOGIN",
            "title": "Login",
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
                        "text": "Welcome Back"
                    },
                    {
                        "type": "TextBody",
                        "text": "Please enter your credentials to log in."
                    },
                    {
                        "type": "Form",
                        "name": "login_form",
                        "children": [
                            {
                                "type": "TextInput",
                                "name": "username",
                                "label": "Username",
                                "required": True,
                                "input-type": "text",
                                "helper-text": "Enter your username"
                            },
                            {
                                "type": "TextInput",
                                "name": "password",
                                "label": "Password",
                                "required": True,
                                "input-type": "password",
                                "helper-text": "Enter your password"
                            },
                            {
                                "type": "Footer",
                                "label": "Login",
                                "on-click-action": {
                                    "name": "data_exchange",
                                    "payload": {
                                        "username": "${form.username}",
                                        "password": "${form.password}",
                                        "action": "login"
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
            "title": "Login Successful",
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
                        "text": "You have been logged in successfully."
                    },
                    {
                        "type": "Footer",
                        "label": "Done",
                        "on-click-action": {
                            "name": "complete",
                            "payload": {
                                "authenticated": "true"
                            }
                        }
                    }
                ]
            }
        }
    ]
}

LOGIN_WHATSAPP_FLOW_METADATA = {
    "name": "login_whatsapp",
    "friendly_name": "Login (Interactive)",
    "description": "Interactive WhatsApp UI flow for user authentication",
    "is_active": True,
}
