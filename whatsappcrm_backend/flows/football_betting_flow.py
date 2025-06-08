from typing import Dict, Any
from flows.models import Flow, FlowStep, FlowTransition

def create_football_betting_flow() -> Dict[str, Any]:
    """Create the football betting flow configuration"""
    return {
        "name": "Football Betting",
        "description": "Flow for handling football betting via WhatsApp",
        "steps": [
            {
                "name": "welcome",
                "type": "send_message",
                "message_config": {
                    "message_type": "text",
                    "text": {
                        "body": (
                            "Welcome to Football Betting! 🎉\n\n"
                            "I can help you:\n"
                            "1. View upcoming matches and odds\n"
                            "2. Create betting tickets\n"
                            "3. Add bets to your ticket\n"
                            "4. View your betting history\n\n"
                            "What would you like to do?"
                        )
                    }
                },
                "transitions": [
                    {
                        "to_step": "view_matches",
                        "condition": "message.text.upper().startswith('MATCHES')"
                    },
                    {
                        "to_step": "new_ticket",
                        "condition": "message.text.upper().startswith('NEW TICKET')"
                    },
                    {
                        "to_step": "add_bet",
                        "condition": "message.text.upper().startswith('ADD')"
                    },
                    {
                        "to_step": "place_ticket",
                        "condition": "message.text.upper().startswith('PLACE TICKET')"
                    },
                    {
                        "to_step": "view_tickets",
                        "condition": "message.text.upper().startswith('MY TICKETS')"
                    },
                    {
                        "to_step": "help",
                        "condition": "message.text.upper().startswith('HELP')"
                    }
                ]
            },
            {
                "name": "view_matches",
                "type": "action",
                "actions_to_run": [
                    {
                        "action_type": "handle_football_betting",
                        "betting_action": "view_matches"
                    }
                ],
                "transitions": [
                    {
                        "to_step": "welcome",
                        "condition": "true"
                    }
                ]
            },
            {
                "name": "new_ticket",
                "type": "action",
                "actions_to_run": [
                    {
                        "action_type": "handle_football_betting",
                        "betting_action": "new_ticket"
                    }
                ],
                "transitions": [
                    {
                        "to_step": "welcome",
                        "condition": "true"
                    }
                ]
            },
            {
                "name": "add_bet",
                "type": "action",
                "actions_to_run": [
                    {
                        "action_type": "handle_football_betting",
                        "betting_action": "add_bet",
                        "bet_details": {
                            "match_id": "{{message.text.split()[1]}}",
                            "market": "{{message.text.split()[2]}}",
                            "outcome": "{{message.text.split()[3]}}",
                            "amount": "{{message.text.split()[4]}}"
                        }
                    }
                ],
                "transitions": [
                    {
                        "to_step": "welcome",
                        "condition": "true"
                    }
                ]
            },
            {
                "name": "place_ticket",
                "type": "action",
                "actions_to_run": [
                    {
                        "action_type": "handle_football_betting",
                        "betting_action": "place_ticket",
                        "bet_details": {
                            "ticket_id": "{{message.text.split()[2]}}"
                        }
                    }
                ],
                "transitions": [
                    {
                        "to_step": "welcome",
                        "condition": "true"
                    }
                ]
            },
            {
                "name": "view_tickets",
                "type": "action",
                "actions_to_run": [
                    {
                        "action_type": "handle_football_betting",
                        "betting_action": "view_tickets"
                    }
                ],
                "transitions": [
                    {
                        "to_step": "welcome",
                        "condition": "true"
                    }
                ]
            },
            {
                "name": "help",
                "type": "send_message",
                "message_config": {
                    "message_type": "text",
                    "text": {
                        "body": (
                            "📱 Football Betting Commands:\n\n"
                            "MATCHES - View upcoming matches and odds\n"
                            "NEW TICKET - Create a new betting ticket\n"
                            "ADD [match_id] [market] [outcome] [amount] - Add a bet to your ticket\n"
                            "PLACE TICKET [ticket_id] - Place all bets in your ticket\n"
                            "MY TICKETS - View your betting tickets\n"
                            "HELP - Show this help message"
                        )
                    }
                },
                "transitions": [
                    {
                        "to_step": "welcome",
                        "condition": "true"
                    }
                ]
            }
        ]
    }

def initialize_football_betting_flow():
    """Initialize the football betting flow in the database"""
    flow_config = create_football_betting_flow()
    
    # Create or update the flow
    flow, created = Flow.objects.update_or_create(
        name=flow_config["name"],
        defaults={
            "description": flow_config["description"],
            "is_active": True
        }
    )
    
    # Clear existing steps and transitions
    flow.steps.all().delete()
    
    # Create steps and transitions
    for step_config in flow_config["steps"]:
        step = FlowStep.objects.create(
            flow=flow,
            name=step_config["name"],
            step_type=step_config["type"],
            config=step_config
        )
        
        # Create transitions
        for transition_config in step_config.get("transitions", []):
            FlowTransition.objects.create(
                from_step=step,
                to_step_name=transition_config["to_step"],
                condition=transition_config["condition"]
            )
    
    return flow 