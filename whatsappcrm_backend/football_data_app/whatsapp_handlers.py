from typing import Dict, Any
from decimal import Decimal
from .football_engine import FootballEngine
from customer_data.models import BetTicket

class FootballWhatsAppHandler:
    def __init__(self):
        self.engine = FootballEngine()

    def handle_message(self, message: str, user_id: int) -> Dict[str, Any]:
        """Handle incoming WhatsApp messages for football betting"""
        message = message.strip().upper()
        
        if message.startswith('MATCHES'):
            # Show upcoming matches
            matches = self.engine.get_upcoming_matches()
            if not matches:
                return {'message': 'No upcoming matches found.'}
            
            response = "⚽ Upcoming Matches:\n\n"
            for match in matches:
                response += self.engine.format_match_message(match)
                response += "\n-------------------\n"
            return {'message': response}

        elif message.startswith('NEW TICKET'):
            # Create a new bet ticket
            ticket = self.engine.create_bet_ticket(user_id)
            return {
                'message': (
                    f"New ticket #{ticket.id} created!\n"
                    "Use ADD [match_id] [market] [outcome] [amount] to add bets.\n"
                    "Use PLACE TICKET [ticket_id] when you're ready to place all bets."
                )
            }

        elif message.startswith('ADD'):
            # Add bet to ticket
            try:
                _, match_id, market, outcome, amount = message.split()
                amount = Decimal(amount)
                
                # Get the latest pending ticket or create a new one
                ticket = BetTicket.objects.filter(
                    user_id=user_id,
                    status='PENDING'
                ).order_by('-created_at').first()
                
                if not ticket:
                    ticket = self.engine.create_bet_ticket(user_id)
                
                result = self.engine.add_bet_to_ticket(
                    ticket_id=ticket.id,
                    match_id=int(match_id),
                    market_category=market,
                    outcome_name=outcome,
                    amount=amount
                )
                return {'message': result['message']}
            except ValueError:
                return {
                    'message': 'Invalid format. Use: ADD [match_id] [market] [outcome] [amount]'
                }

        elif message.startswith('PLACE TICKET'):
            # Place all bets in a ticket
            try:
                _, ticket_id = message.split()
                result = self.engine.place_ticket(int(ticket_id))
                return {'message': result['message']}
            except ValueError:
                return {
                    'message': 'Invalid format. Use: PLACE TICKET [ticket_id]'
                }

        elif message.startswith('MY TICKETS'):
            # Show betting history
            tickets = self.engine.get_user_tickets(user_id)
            response = self.engine.format_ticket_history_message(tickets)
            return {'message': response}

        elif message.startswith('HELP'):
            return {
                'message': (
                    "📱 Football Betting Commands:\n\n"
                    "MATCHES - View upcoming matches and odds\n"
                    "NEW TICKET - Create a new betting ticket\n"
                    "ADD [match_id] [market] [outcome] [amount] - Add a bet to your ticket\n"
                    "PLACE TICKET [ticket_id] - Place all bets in your ticket\n"
                    "MY TICKETS - View your betting tickets\n"
                    "HELP - Show this help message"
                )
            }

        else:
            return {
                'message': (
                    "Welcome to Football Betting!\n"
                    "Type HELP to see available commands."
                )
            } 