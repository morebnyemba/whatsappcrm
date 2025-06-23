# whatsappcrm_backend/flows/deposit_flow.py

def create_deposit_flow():
    """
    Defines a flow for handling various types of deposits (manual, EcoCash, Innbucks, Omari).
    """
    return {
        "name": "Deposit Flow",
        "description": "Guides the user through making a deposit using various methods.",
        "trigger_keywords": ["deposit", "topup", "add funds", "fund wallet"],
        "is_active": True,
        "steps": [
            {
                "name": "ensure_customer_account",
                "step_type": "action",
                "is_entry_point": True, # This becomes the new entry point
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "create_account",
                            # Optionally, you can pass templates for email, first_name, etc.
                            # For now, let's rely on the utility's defaults or what it can infer.
                            # The utility will use contact.whatsapp_id as username if no email.
                            # "email_template": "{{ contact.email }}", # If contact has an email field
                            # "first_name_template": "{{ contact.name }}" # If you want to parse name
                        }
                    ]
                },
                "transitions": [
                    {"to_step": "start_deposit", "priority": 1, "condition_config": {"type": "variable_equals", "variable_name": "account_creation_status", "value": True}},
                    {"to_step": "account_creation_failed", "priority": 99, "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "start_deposit",
                "step_type": "question", # Changed from send_message to question
                "is_entry_point": False, # No longer the entry point
                "config": {
                    "message_config": { # Wrapped interactive message config
                        "message_type": "interactive",
                        "interactive": {
                            "type": "list",
                            "body": {"text": "How would you like to deposit funds into your wallet?"},
                            "action": {
                                "button": "Menu",
                                "sections": [
                                    {
                                        "title": "Available Methods",
                                        "rows": [
                                            {"id": "deposit_manual", "title": "Manual Deposit", "description": "Deposit with admin approval"},
                                            {"id": "deposit_ecocash", "title": "EcoCash", "description": "Pay via EcoCash mobile money"},
                                            {"id": "deposit_innbucks", "title": "Innbucks", "description": "Pay via Innbucks mobile money"},
                                            {"id": "deposit_omari", "title": "Omari", "description": "Pay via Omari mobile money"},
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    "reply_config": { # Added reply_config
                        "save_to_variable": "selected_deposit_method_id", # Save the selected ID to context
                        "expected_type": "interactive_id" # Expect an interactive reply ID
                    },
                    "fallback_config": { # Added fallback_config for question step
                        "max_retries": 2,
                        "re_prompt_message_text": "Please select a valid deposit method from the list.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid option too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "ask_manual_amount",
                        "priority": 1, # This is a high priority (low number)
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "deposit_manual"}
                    },
                    {
                        "to_step": "ask_ecocash_amount",
                        "priority": 1, # This is a high priority (low number)
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "deposit_ecocash"}
                    },
                    {
                        "to_step": "ask_innbucks_amount",
                        "priority": 1, # This is a high priority (low number)
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "deposit_innbucks"}
                    },
                    {
                        "to_step": "ask_omari_amount",
                        "priority": 1, # This is a high priority (low number)
                        "condition_config": {"type": "interactive_reply_id_equals", "value": "deposit_omari"}
                    },
                    {
                        "to_step": "deposit_failed",
                        "priority": 99, # This is a low priority (high number) for the fallback
                        "condition_config": {"type": "always_true"}, # Fallback for invalid interactive reply
                        "config": {"message": "Invalid deposit method selected. Please try again."}
                    }
                ]
            },
            # --- Manual Deposit Path ---
            {
                "name": "ask_manual_amount",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter the amount you wish to deposit manually (e.g., 10.00):"}
                    },
                    "reply_config": {
                        "save_to_variable": "deposit_amount",
                        "expected_type": "number",
                        "validation_regex": r"^\d+(\.\d{1,2})?$" # Allows integers or decimals with up to 2 decimal places
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "That doesn't look like a valid amount. Please enter a number, e.g., 50.00.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid amount too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "perform_manual_deposit",
                        "priority": 0, # Explicitly set highest priority for valid reply
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_deposit_flow", # Fallback if max retries reached
                        "priority": 99, # Set a lower priority (higher number) for the fallback
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "perform_manual_deposit",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "perform_deposit",
                            "amount_template": "{{ flow_context.deposit_amount }}",
                            "payment_method": "manual",
                            "description_template": "Manual deposit via WhatsApp flow"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "deposit_success",
                        "priority": 0, # Explicitly set highest priority for success
                        "condition_config": {"type": "variable_equals", "variable_name": "deposit_status", "value": True}
                    },
                    {
                        "to_step": "deposit_failed",
                        "priority": 1, # Explicitly set lower priority for fallback
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # --- EcoCash Deposit Path ---
            {
                "name": "ask_ecocash_amount",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter the amount you wish to deposit via EcoCash (e.g., 25.00):"}
                    },
                    "reply_config": {
                        "save_to_variable": "deposit_amount",
                        "expected_type": "number",
                        "validation_regex": r"^\d+(\.\d{1,2})?$"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Invalid amount. Please enter a number, e.g., 25.00.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid amount too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "ask_ecocash_phone",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_deposit_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "ask_ecocash_phone",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter your EcoCash phone number (e.g., 263771234567):"}
                    },
                    "reply_config": {
                        "save_to_variable": "deposit_phone_number",
                        "expected_type": "number",
                        "validation_regex": r"^\d{10,15}$" # Basic phone number validation
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Invalid phone number. Please enter a valid mobile number (e.g., 263771234567).",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid phone number too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "initiate_ecocash_deposit",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_deposit_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "initiate_ecocash_deposit",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "perform_deposit",
                            "amount_template": "{{ flow_context.deposit_amount }}",
                            "payment_method": "paynow_mobile",
                            "phone_number_template": "{{ flow_context.deposit_phone_number }}",
                            "paynow_method_type_template": "ecocash", # Specific Paynow method type
                            "description_template": "EcoCash deposit via WhatsApp flow"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "payment_initiated_message",
                        "priority": 0, # Higher priority for success, now points to the new message step
                        "condition_config": {"type": "variable_equals", "variable_name": "deposit_status", "value": True} # Check for success
                    },
                    {
                        "to_step": "deposit_failed",
                        "priority": 1, # Lower priority for fallback
                        "condition_config": {"type": "always_true"} # Fallback if not successful
                    }
                ]
            },
            # --- Innbucks Deposit Path (similar to EcoCash) ---
            {
                "name": "ask_innbucks_amount",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter the amount you wish to deposit via Innbucks (e.g., 15.00):"}
                    },
                    "reply_config": {
                        "save_to_variable": "deposit_amount",
                        "expected_type": "number",
                        "validation_regex": r"^\d+(\.\d{1,2})?$"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Invalid amount. Please enter a number, e.g., 15.00.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid amount too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "ask_innbucks_phone",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_deposit_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "ask_innbucks_phone",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter your Innbucks phone number (e.g., 263771234567):"}
                    },
                    "reply_config": {
                        "save_to_variable": "deposit_phone_number",
                        "expected_type": "number",
                        "validation_regex": r"^\d{10,15}$"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Invalid phone number. Please enter a valid mobile number (e.g., 263771234567).",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid phone number too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "initiate_innbucks_deposit",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_deposit_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "initiate_innbucks_deposit",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "perform_deposit",
                            "amount_template": "{{ flow_context.deposit_amount }}",
                            "payment_method": "paynow_mobile",
                            "phone_number_template": "{{ flow_context.deposit_phone_number }}",
                            "paynow_method_type_template": "innbucks", # Specific Paynow method type
                            "description_template": "Innbucks deposit via WhatsApp flow"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "payment_initiated_message",
                        "priority": 0, # Higher priority for success
                        "condition_config": {"type": "variable_equals", "variable_name": "deposit_status", "value": True}
                    },
                    {
                        "to_step": "deposit_failed",
                        "priority": 1, # Lower priority for fallback
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            # --- Omari Deposit Path (similar to EcoCash) ---
            {
                "name": "ask_omari_amount",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter the amount you wish to deposit via Omari (e.g., 30.00):"}
                    },
                    "reply_config": {
                        "save_to_variable": "deposit_amount",
                        "expected_type": "number",
                        "validation_regex": r"^\d+(\.\d{1,2})?$"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Invalid amount. Please enter a number, e.g., 30.00.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid amount too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "ask_omari_phone",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_deposit_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "ask_omari_phone",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter your Omari phone number (e.g., 263771234567):"}
                    },
                    "reply_config": {
                        "save_to_variable": "deposit_phone_number",
                        "expected_type": "number",
                        "validation_regex": r"^\d{10,15}$"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Invalid phone number. Please enter a valid mobile number (e.g., 263771234567).",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid phone number too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "initiate_omari_deposit",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_deposit_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "initiate_omari_deposit",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "perform_deposit",
                            "amount_template": "{{ flow_context.deposit_amount }}",
                            "payment_method": "paynow_mobile",
                            "phone_number_template": "{{ flow_context.deposit_phone_number }}",
                            "paynow_method_type_template": "omari", # Specific Paynow method type
                            "description_template": "Omari deposit via WhatsApp flow"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "payment_initiated_message",
                        "priority": 0, # Higher priority for success
                        "condition_config": {"type": "variable_equals", "variable_name": "deposit_status", "value": True} # Check for success
                    },
                    {
                        "to_step": "deposit_failed",
                        "priority": 1, # Lower priority for fallback
                        "condition_config": {"type": "always_true"} # Fallback if not successful
                    }
                ]
            },
            {
                "name": "payment_initiated_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "{{ flow_context.deposit_message }}"}
                },
                "transitions": [ # This transition is correct as the polling task sends the final message
                    {"to_step": "end_deposit_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "deposit_success",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "{% if flow_context.payment_method == 'manual' %}\n"
                                "✅ Your manual deposit request for ${{ flow_context.deposit_amount|floatformat:2 }} has been received and is pending approval. You will be notified once it's processed.\n"
                                "{% else %}\n"
                                "🎉 Deposit successful! Your new balance is: ${{ flow_context.current_balance|floatformat:2 }}\n\nThank you for topping up!\n"
                                "{% endif %}"
                    }
                },
                "transitions": [ # Explicitly set priority
                    {"to_step": "end_deposit_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "deposit_failed",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "❌ Deposit failed: {{ flow_context.deposit_message | default:'An unknown error occurred.' }}\n\nPlease try again or contact support."
                    }
                },
                "transitions": [ # Explicitly set priority
                    {"to_step": "end_deposit_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "end_deposit_flow",
                "step_type": "end_flow",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Thank you for using our deposit service. Have a great day!"}
                    }
                },
                "transitions": []
            }
        ]
    }
