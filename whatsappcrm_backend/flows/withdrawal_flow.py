def create_withdrawal_flow():
    """
    Defines a flow for handling user-initiated withdrawals.
    """
    return {
        "name": "Withdrawal Flow",
        "description": "Guides the user through requesting a withdrawal.",
        "trigger_keywords": ["withdraw", "cash out", "get money"],
        "is_active": True,
        "steps": [
            {
                "name": "ensure_customer_account_withdrawal",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "create_account",
                        }
                    ]
                },
                "transitions": [
                    {"to_step": "check_balance_for_withdrawal", "priority": 1, "condition_config": {"type": "variable_equals", "variable_name": "account_creation_status", "value": True}},
                    {"to_step": "account_creation_failed_withdrawal", "priority": 99, "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "account_creation_failed_withdrawal",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "We couldn't set up your account. Please contact support to proceed with withdrawals."}
                },
                "transitions": [
                    {"to_step": "end_withdrawal_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "check_balance_for_withdrawal",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "set_context_variable",
                            "variable_name": "current_wallet_balance",
                            "value_template": "{{ customer_data.utils.get_customer_wallet_balance(contact.whatsapp_id).balance }}"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "ask_withdrawal_amount",
                        "priority": 1,
                        "condition_config": {"type": "variable_exists", "variable_name": "current_wallet_balance"}
                    },
                    {
                        "to_step": "withdrawal_failed_message",
                        "priority": 99,
                        "condition_config": {"type": "always_true"},
                        "config": {"message": "Could not retrieve your balance. Please try again later."}
                    }
                ]
            },
            {
                "name": "ask_withdrawal_amount",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Your current balance is: ${{ flow_context.current_wallet_balance|floatformat:2 }}\n\nPlease enter the amount you wish to withdraw (e.g., 10.00):"}
                    },
                    "reply_config": {
                        "save_to_variable": "withdrawal_amount",
                        "expected_type": "number",
                        "validation_regex": r"^\d+(\.\d{1,2})?$"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "That doesn't look like a valid amount. Please enter a number, e.g., 10.00.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "You've entered an invalid amount too many times. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "validate_withdrawal_amount",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_withdrawal_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "validate_withdrawal_amount",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "set_context_variable",
                            "variable_name": "withdrawal_amount_float",
                            "value_template": "{{ flow_context.withdrawal_amount|float }}"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "ask_ecocash_phone_withdrawal",
                        "priority": 1,
                        "condition_config": {"type": "variable_exists", "variable_name": "withdrawal_amount_float", "value": True}
                    },
                    {
                        "to_step": "withdrawal_failed_message",
                        "priority": 99,
                        "condition_config": {"type": "always_true"},
                        "config": {"message": "Invalid withdrawal amount. Please try again."}
                    }
                ]
            },
            {
                "name": "ask_ecocash_phone_withdrawal",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Please enter the EcoCash phone number for your withdrawal (e.g., 263771234567):"}
                    },
                    "reply_config": {
                        "save_to_variable": "withdrawal_phone_number",
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
                        "to_step": "confirm_withdrawal_details",
                        "priority": 0,
                        "condition_config": {"type": "question_reply_is_valid", "value": True}
                    },
                    {
                        "to_step": "end_withdrawal_flow",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "confirm_withdrawal_details",
                "step_type": "question",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {
                            "body": "You are requesting to withdraw ${{ flow_context.withdrawal_amount|floatformat:2 }} to EcoCash number {{ flow_context.withdrawal_phone_number }}.\n\nIs this correct? (Yes/No)"
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "withdrawal_confirmation",
                        "expected_type": "text",
                        "validation_regex": r"^(?i)(yes|no)$"
                    },
                    "fallback_config": {
                        "max_retries": 2,
                        "re_prompt_message_text": "Please reply 'Yes' or 'No'.",
                        "action_after_max_retries": "end_flow",
                        "end_flow_message_text": "Confirmation failed. Please try again later."
                    }
                },
                "transitions": [
                    {
                        "to_step": "initiate_withdrawal_request",
                        "priority": 0,
                        "condition_config": {"type": "user_reply_matches_keyword", "keyword": "yes", "case_sensitive": False}
                    },
                    {
                        "to_step": "withdrawal_cancelled_message",
                        "priority": 1,
                        "condition_config": {"type": "user_reply_matches_keyword", "keyword": "no", "case_sensitive": False}
                    },
                    {
                        "to_step": "end_withdrawal_flow",
                        "priority": 99,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "initiate_withdrawal_request",
                "step_type": "action",
                "config": {
                    "actions_to_run": [
                        {
                            "action_type": "perform_withdrawal",
                            "amount_template": "{{ flow_context.withdrawal_amount }}",
                            "payment_method": "ecocash",
                            "phone_number_template": "{{ flow_context.withdrawal_phone_number }}",
                            "description_template": "EcoCash withdrawal via WhatsApp flow"
                        }
                    ]
                },
                "transitions": [
                    {
                        "to_step": "withdrawal_request_received_message",
                        "priority": 0,
                        "condition_config": {"type": "variable_equals", "variable_name": "withdrawal_status", "value": True}
                    },
                    {
                        "to_step": "withdrawal_failed_message",
                        "priority": 1,
                        "condition_config": {"type": "always_true"}
                    }
                ]
            },
            {
                "name": "withdrawal_request_received_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "{{ flow_context.withdrawal_message }}"}
                },
                "transitions": [
                    {"to_step": "end_withdrawal_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "withdrawal_cancelled_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {"body": "Your withdrawal request has been cancelled. You can start a new request anytime."}
                },
                "transitions": [
                    {"to_step": "end_withdrawal_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "withdrawal_failed_message",
                "step_type": "send_message",
                "config": {
                    "message_type": "text",
                    "text": {
                        "body": "❌ Withdrawal failed: {{ flow_context.withdrawal_message | default:'An unknown error occurred.' }}\n\nPlease try again or contact support."
                    }
                },
                "transitions": [
                    {"to_step": "end_withdrawal_flow", "condition_config": {"type": "always_true"}}
                ]
            },
            {
                "name": "end_withdrawal_flow",
                "step_type": "end_flow",
                "config": {
                    "message_config": {
                        "message_type": "text",
                        "text": {"body": "Thank you for using our withdrawal service. Have a great day!"}
                    }
                },
                "transitions": []
            }
        ]
    }