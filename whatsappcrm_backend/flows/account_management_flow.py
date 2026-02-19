# whatsappcrm_backend/flows/account_management_flow.py

def create_account_management_flow():
    """
    Defines the flow for managing a user's account (deposit, withdraw, etc.).
    """
    return {
        "name": "Account Management Flow",
        "description": "A sub-menu for account-related actions like deposit and withdrawal.",
        "trigger_keywords": ["account", "manage account"],
        "is_active": True,
        "steps": [
            {
                "name": "show_account_menu",
                "step_type": "question",
                "is_entry_point": True,
                "config": {
                    "message_config": {
                        "message_type": "interactive",
                        "interactive": {
                            "type": "list",
                            "header": {"type": "text", "text": "Account Management"},
                            "body": {"text": "What would you like to do with your account?"},
                            "footer": {"text": "Select an option"},
                            "action": {
                                "button": "Options",
                                "sections": [
                                    {
                                        "title": "Wallet Actions",
                                        "rows": [
                                            {"id": "account_deposit", "title": "Deposit Funds", "description": "Add money to your wallet"},
                                            {"id": "account_withdraw", "title": "Withdraw Funds", "description": "Request a withdrawal"},
                                            {"id": "account_check_balance", "title": "Check Balance", "description": "View your current balance"},
                                            {"id": "account_agent_program", "title": "Agent Program", "description": "Earn commission on your referrals' lost bets"},
                                        ]
                                    },
                                    {
                                        "title": "Navigation",
                                        "rows": [
                                            {"id": "account_back_to_main", "title": "Back to Main Menu", "description": "Return to the main menu"},
                                        ]
                                    }
                                ]
                            }
                        }
                    },
                    "reply_config": {
                        "save_to_variable": "selected_account_option",
                        "expected_type": "interactive_id"
                    }
                },
                "transitions": [
                    {"to_step": "switch_to_deposit", "condition_config": {"type": "interactive_reply_id_equals", "value": "account_deposit"}},
                    {"to_step": "switch_to_withdrawal", "condition_config": {"type": "interactive_reply_id_equals", "value": "account_withdraw"}},
                    {"to_step": "fetch_wallet_balance", "condition_config": {"type": "interactive_reply_id_equals", "value": "account_check_balance"}},
                    {"to_step": "switch_to_agent_program", "condition_config": {"type": "interactive_reply_id_equals", "value": "account_agent_program"}},
                    {"to_step": "switch_to_welcome", "condition_config": {"type": "interactive_reply_id_equals", "value": "account_back_to_main"}},
                ]
            },
            # --- Switch Flow Actions ---
            {
                "name": "switch_to_deposit",
                "step_type": "action",
                "config": {"actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "deposit"}]},
                "transitions": []
            },
            {
                "name": "switch_to_withdrawal",
                "step_type": "action",
                "config": {"actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "withdraw"}]},
                "transitions": []
            },
            {
                "name": "switch_to_welcome",
                "step_type": "action",
                "config": {"actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "menu"}]},
                "transitions": []
            },
            {
                "name": "switch_to_agent_program",
                "step_type": "action",
                "config": {
                    "actions_to_run": [{"action_type": "switch_flow", "trigger_keyword_template": "agent"}]
                },
                "transitions": []
            },
            # --- Balance Check Path ---
            {
                "name": "fetch_wallet_balance",
                "step_type": "action",
                "config": {"actions_to_run": [{"action_type": "handle_betting_action", "betting_action": "check_wallet_balance"}]},
                "transitions": [{"to_step": "display_balance", "condition_config": {"type": "always_true"}}]
            },
            {
                "name": "display_balance",
                "step_type": "send_message",
                "config": {"message_type": "text", "text": {"body": "{{ flow_context.check_wallet_balance_message }}"}},
                "transitions": [{"to_step": "end_account_flow", "condition_config": {"type": "always_true"}}]
            },
            # --- End Flow Step ---
            {
                "name": "end_account_flow",
                "step_type": "end_flow",
                "config": {}
            }
        ]
    }