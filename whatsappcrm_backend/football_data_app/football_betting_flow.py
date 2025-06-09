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
                            "2. Place bets\n"
                            "3. Check your betting history\n\n"
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
                        "to_step": "place_bet",
                        "condition": "message.text.upper().startswith('BET')"
                    },
                    {
                        "to_step": "view_bets",
                        "condition": "message.text.upper().startswith('MY BETS')"
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
                "name": "place_bet",
                "type": "action",
                "actions_to_run": [
                    {
                        "action_type": "handle_football_betting",
                        "betting_action": "place_bet",
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
                "name": "view_bets",
                "type": "action",
                "actions_to_run": [
                    {
                        "action_type": "handle_football_betting",
                        "betting_action": "view_bets"
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
                            "BET [match_id] [market] [outcome] [amount] - Place a bet\n"
                            "MY BETS - View your betting history\n"
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
        # Extract the step configuration
        step_type = step_config["type"]
        step_name = step_config["name"]
        
        # Create the step with proper configuration
        step = FlowStep.objects.create(
            flow=flow,
            name=step_name,
            step_type=step_type,
            config=step_config  # Store the entire step config in the config field
        )
        
        # Create transitions
        for transition_config in step_config.get("transitions", []):
            FlowTransition.objects.create(
                from_step=step,
                to_step_name=transition_config["to_step"],
                condition=transition_config["condition"]
            )
    
    return flow 