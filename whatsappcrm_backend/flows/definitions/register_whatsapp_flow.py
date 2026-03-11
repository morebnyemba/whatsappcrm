# whatsappcrm_backend/flows/definitions/register_whatsapp_flow.py

"""
WhatsApp UI Flow JSON definition for User Registration.

This is the interactive registration form presented natively in WhatsApp
via Meta's Flow JSON schema.  The backend data-exchange endpoint at
``/crm-api/meta/flow-endpoint/`` handles account creation.

Screens:
    1. REGISTER  – collects username, email, password, confirm password,
                   first name, last name, date of birth, gender, referral code
    2. COMPLETE  – terminal screen confirming registration
"""

REGISTER_WHATSAPP_FLOW = {
    "version": "6.0",
    "data_api_version": "3.0",
    "routing_model": {"REGISTER": ["COMPLETE"]},
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
                        "type": "TextBody",
                        "text": "${data.error_message}",
                        "visible": "${data.error_message != \"\"}"
                    },
                    {
                        "type": "Form",
                        "name": "register_form",
                        "children": [
                            {
                                "type": "TextInput",
                                "name": "first_name",
                                "label": "First Name",
                                "required": True,
                                "input-type": "text",
                                "helper-text": "Enter your first name"
                            },
                            {
                                "type": "TextInput",
                                "name": "last_name",
                                "label": "Last Name",
                                "required": True,
                                "input-type": "text",
                                "helper-text": "Enter your last name"
                            },
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
                                "type": "Dropdown",
                                "name": "gender",
                                "label": "Gender",
                                "required": False,
                                "options": [
                                    {"id": "M", "title": "Male"},
                                    {"id": "F", "title": "Female"},
                                    {"id": "O", "title": "Other"}
                                ]
                            },
                            {
                                "type": "TextInput",
                                "name": "date_of_birth",
                                "label": "Date of Birth",
                                "required": False,
                                "input-type": "text",
                                "helper-text": "Format: YYYY-MM-DD (e.g. 1990-01-31)"
                            },
                            {
                                "type": "TextInput",
                                "name": "referral_code",
                                "label": "Referral Code (Optional)",
                                "required": False,
                                "input-type": "text",
                                "helper-text": "Enter a referral code if you have one"
                            },
                            {
                                "type": "Footer",
                                "label": "Register",
                                "on-click-action": {
                                    "name": "data_exchange",
                                    "payload": {
                                        "first_name": "${form.first_name}",
                                        "last_name": "${form.last_name}",
                                        "username": "${form.username}",
                                        "email": "${form.email}",
                                        "password": "${form.password}",
                                        "confirm_password": "${form.confirm_password}",
                                        "gender": "${form.gender}",
                                        "date_of_birth": "${form.date_of_birth}",
                                        "referral_code": "${form.referral_code}",
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
                        "text": "Your account has been created successfully. You can now start using the service."
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
