from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional
from django.db.models import Q
from django.utils import timezone
from .models import (
    League, Team, FootballFixture, Bookmaker,
    Market, MarketOutcome
)
from customer_data.models import UserWallet, WalletTransaction, Bet, BetTicket

class FootballEngine:
    def __init__(self):
        # Use get_or_create to ensure the default bookmaker exists
        self.default_bookmaker, _ = Bookmaker.objects.get_or_create(
            api_bookmaker_key='default',
            defaults={'name': 'Default Bookmaker'} # Provide default name if creating
        )

    def get_upcoming_matches(self, days_ahead: int = 7) -> List[Dict]:
        """Get upcoming matches with their odds for WhatsApp display"""
        end_date = timezone.now() + timedelta(days=days_ahead)
        fixtures = FootballFixture.objects.filter(
            match_date__gte=timezone.now(), # Use match_date
            match_date__lte=end_date, # Use match_date
            status=FootballFixture.FixtureStatus.SCHEDULED # Use the correct enum for status
        ).select_related('league', 'home_team', 'away_team')

        matches_data = []
        for fixture in fixtures:
            match_data = {
                'id': fixture.id,
                'league': fixture.league.name,
                'home_team': fixture.home_team.name, # Access name from related Team object
                'away_team': fixture.away_team.name, # Access name from related Team object
                'start_time': fixture.match_date.strftime('%Y-%m-%d %H:%M'), # Use match_date
                'markets': self._get_markets_for_fixture(fixture)
            }
            matches_data.append(match_data)
        return matches_data

    def _get_markets_for_fixture(self, fixture: FootballFixture) -> List[Dict]:
        """Get available betting markets for a fixture"""
        markets = Market.objects.filter(
            fixture=fixture, # Use 'fixture' field
            bookmaker=self.default_bookmaker
        ).select_related('category').prefetch_related('outcomes')

        market_data = []
        for market in markets:
            market_info = {
                'category': market.category.name,
                'outcomes': [
                    {
                        'name': outcome.outcome_name,
                        'odds': float(outcome.odds),
                        'point_value': float(outcome.point_value) if outcome.point_value else None
                    }
                    for outcome in market.outcomes.all()
                ]
            }
            market_data.append(market_info)
        return market_data

    def format_match_message(self, match_data: Dict) -> str:
        """Format match data for WhatsApp message"""
        message = f"🏆 {match_data['league']}\n"
        message += f"⚽ {match_data['home_team']} vs {match_data['away_team']}\n"
        message += f"🕒 {match_data['start_time']}\n\n"
        message += "Available Markets:\n"
        
        for market in match_data['markets']:
            message += f"\n{market['category']}:\n"
            for outcome in market['outcomes']:
                odds_str = f"({outcome['odds']})"
                if outcome['point_value']:
                    odds_str = f"{outcome['point_value']} {odds_str}"
                message += f"- {outcome['name']}: {odds_str}\n"
        
        message += "\nTo add to your ticket, reply with:\n"
        message += "ADD [match_id] [market] [outcome] [amount]"
        return message

    def create_bet_ticket(self, user_id: int) -> BetTicket:
        """Create a new bet ticket for a user"""
        return BetTicket.objects.create(
            user_id=user_id,
            total_stake=Decimal('0.00'),
            potential_winnings=Decimal('0.00')
        )

    def add_bet_to_ticket(self, ticket_id: int, match_id: int, 
                         market_category: str, outcome_name: str, 
                         amount: Decimal) -> Dict:
        """Add a bet to an existing ticket"""
        try:
            ticket = BetTicket.objects.get(id=ticket_id, status='PENDING')
            fixture = FootballFixture.objects.get(id=match_id)
            market = Market.objects.get(
                fixture=fixture, # Use 'fixture' field
                category__name=market_category,
                bookmaker=self.default_bookmaker
            )
            outcome = MarketOutcome.objects.get(
                market=market,
                outcome_name=outcome_name
            )

            # Create bet
            bet = Bet.objects.create(
                ticket=ticket,
                market_outcome=outcome,
                amount=amount
            )
            bet.place_bet()

            # Update ticket total stake
            ticket.total_stake += amount
            ticket.calculate_potential_winnings()

            return {
                'success': True,
                'message': (
                    f"Bet added to ticket #{ticket.id}!\n"
                    f"Match: {fixture}\n"
                    f"Market: {market_category}\n"
                    f"Outcome: {outcome_name}\n"
                    f"Amount: ${amount}\n"
                    f"Current ticket total: ${ticket.total_stake}\n"
                    f"Potential winnings: ${ticket.potential_winnings}"
                )
            }

        except BetTicket.DoesNotExist:
            return {'success': False, 'message': 'Ticket not found or already placed'}
        except FootballFixture.DoesNotExist:
            return {'success': False, 'message': 'Match not found'}
        except Market.DoesNotExist:
            return {'success': False, 'message': 'Market not found'}
        except MarketOutcome.DoesNotExist:
            return {'success': False, 'message': 'Outcome not found'}
        except ValueError as e:
            return {'success': False, 'message': str(e)}

    def place_ticket(self, ticket_id: int) -> Dict:
        """Place all bets in a ticket"""
        try:
            ticket = BetTicket.objects.get(id=ticket_id, status='PENDING')
            ticket.place_ticket()
            return {
                'success': True,
                'message': (
                    f"Ticket #{ticket.id} placed successfully!\n"
                    f"Total stake: ${ticket.total_stake}\n"
                    f"Potential winnings: ${ticket.potential_winnings}"
                )
            }
        except BetTicket.DoesNotExist:
            return {'success': False, 'message': 'Ticket not found or already placed'}
        except ValueError as e:
            return {'success': False, 'message': str(e)}

    def get_user_tickets(self, user_id: int) -> List[Dict]:
        """Get user's betting tickets"""
        tickets = BetTicket.objects.filter(
            user_id=user_id
        ).prefetch_related(
            'bets__market_outcome__market__fixture', # Use 'fixture' field
            'bets__market_outcome__market__category'
        ).order_by('-created_at')

        return [{
            'id': ticket.id,
            'total_stake': float(ticket.total_stake),
            'potential_winnings': float(ticket.potential_winnings),
            'status': ticket.status,
            'created_at': ticket.created_at.strftime('%Y-%m-%d %H:%M'),
            'bets': [{
                'match': bet.market_outcome.market.fixture.__str__(), # Use 'fixture' field
                'market': bet.market_outcome.market.category.name,
                'outcome': bet.market_outcome.outcome_name,
                'amount': float(bet.amount),
                'potential_winnings': float(bet.potential_winnings),
                'status': bet.status
            } for bet in ticket.bets.all()]
        } for ticket in tickets]

    def format_ticket_history_message(self, tickets: List[Dict]) -> str:
        """Format betting ticket history for WhatsApp message"""
        if not tickets:
            return "You haven't placed any tickets yet."

        message = "📊 Your Betting Tickets:\n\n"
        for ticket in tickets:
            message += f"Ticket #{ticket['id']}\n"
            message += f"Status: {ticket['status']}\n"
            message += f"Total Stake: ${ticket['total_stake']}\n"
            message += f"Potential Winnings: ${ticket['potential_winnings']}\n"
            message += f"Created: {ticket['created_at']}\n\n"
            message += "Bets:\n"
            for bet in ticket['bets']:
                message += f"- {bet['match']}\n"
                message += f"  {bet['market']}: {bet['outcome']}\n"
                message += f"  Amount: ${bet['amount']}\n"
                message += f"  Status: {bet['status']}\n"
            message += "-------------------\n"
        return message 