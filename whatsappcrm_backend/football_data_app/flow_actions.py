# whatsappcrm_backend/football_data_app/flow_actions.py

from conversations.models import Contact
from decimal import Decimal
from django.contrib.auth.models import User
import logging
from customer_data.models import CustomerProfile, UserWallet, BetTicket
from customer_data.ticket_processing import process_bet_ticket_submission
from customer_data.utils import create_or_get_customer_account, get_customer_wallet_balance
# IMPORTANT: Using 'FootballFixture' as the main fixture model name
from .models import FootballFixture, MarketOutcome # Import FootballFixture directly
from .football_engine import FootballEngine # Retained for other specific engine operations if any
from .utils import get_formatted_football_data, parse_betting_string
from typing import Optional, List
from django.utils import timezone # For footer timestamp in view_my_tickets


logger = logging.getLogger(__name__)

def generate_strong_password():
    return User.objects.make_random_password()


def handle_football_betting_action(
    contact: Contact,
    action_type: str,
    flow_context: dict,
    stake: float = None,
    market_outcome_id: str = None,
    ticket_id: str = None,
    raw_bet_string: str = None, # For place_ticket and parse_and_confirm_ticket
    league_code: Optional[str] = None,
    days_ahead: int = 10,
    days_past: int = 2,
    **kwargs
) -> dict:
    """
    Handles various football betting related actions triggered by a flow.

    For actions returning long messages (view_matches, view_results, view_my_tickets),
    the 'message' field in the result will be a list of strings (message parts).

    Args:
        contact (Contact): The contact object.
        action_type (str): The specific betting action to perform.
        flow_context (dict): The current flow context, useful for storing/retrieving data.
        stake (float, optional): The stake amount for a bet/ticket.
        market_outcome_id (str, optional): The ID of the market outcome for a bet.
        ticket_id (str, optional): The ID of the bet ticket (primarily for context tracking).
        raw_bet_string (str, optional): The raw message string containing betting details.
        league_code (str, optional): League code for filtering matches/results.
        days_ahead (int): Number of days ahead to fetch scheduled matches.
        days_past (int): Number of days past to fetch finished results.
        kwargs: Additional arguments for specific actions.

    Returns:
        dict: A dictionary containing success status, message, and updated context data.
    """
    engine = FootballEngine()
    result = {"success": False, "message": "Unknown betting action.", "data": {}}

    try:
        # Ensure user account and wallet exist using the centralized utility
        account_info = create_or_get_customer_account(contact.whatsapp_id)
        if not account_info.get('success'):
            return {"success": False, "message": account_info.get('message', 'Failed to create or retrieve account.'), "data": {}}
        
        customer_profile = account_info.get('customer_profile')
        user_wallet = account_info.get('wallet')

        if action_type == 'view_matches':
            formatted_matches_parts = get_formatted_football_data(
                data_type="scheduled_fixtures",
                league_code=league_code,
                days_ahead=days_ahead
            )
            result = {
                "success": True,
                "message": formatted_matches_parts, # List of strings
                "data": {"matches_display_parts": formatted_matches_parts}
            }
        elif action_type == 'view_results':
             formatted_results_parts = get_formatted_football_data(
                data_type="finished_results",
                league_code=league_code,
                days_past=days_past
            )
             result = {
                "success": True,
                "message": formatted_results_parts, # List of strings
                "data": {"results_display_parts": formatted_results_parts}
            }
        elif action_type == 'create_new_ticket':
            if 'current_ticket_id' not in flow_context:
                temp_ticket_id = f"temp_{contact.whatsapp_id}_{len(flow_context.get('bets_in_progress', [])) + 1}"
                flow_context['current_ticket_id'] = temp_ticket_id
                flow_context['bets_in_progress'] = []
                result = {
                    "success": True,
                    "message": "New betting ticket initiated. Please add bets.",
                    "data": {"current_ticket_id": temp_ticket_id}
                }
            else:
                 result = {
                    "success": True,
                    "message": "You already have a ticket in progress. Add more bets or place it.",
                    "data": {"current_ticket_id": flow_context['current_ticket_id']}
                }
        elif action_type == 'add_bet_to_ticket':
            if not market_outcome_id:
                return {"success": False, "message": "Market outcome ID is required to add a bet.", "data": {}}

            if 'current_ticket_id' not in flow_context:
                flow_context['current_ticket_id'] = f"temp_{contact.whatsapp_id}_1"
                flow_context['bets_in_progress'] = []

            try:
                # Direct lookup for outcome details based on its integer ID
                outcome_obj = MarketOutcome.objects.select_related('market__fixture__home_team', 'market__fixture__away_team').get(id=int(market_outcome_id))
                # Access fixture details via market__fixture
                bet_data = {
                    'fixture_id': outcome_obj.market.fixture.id, # Accessing id from FootballFixture
                    'home_team': outcome_obj.market.fixture.home_team.name,
                    'away_team': outcome_obj.market.fixture.away_team.name,
                    'outcome_name': outcome_obj.outcome_name,
                    'odds': float(outcome_obj.odds)
                }
            except MarketOutcome.DoesNotExist:
                return {"success": False, "message": "Invalid market outcome ID.", "data": {}}

            if bet_data:
                flow_context['bets_in_progress'].append({
                    'market_outcome_id': market_outcome_id,
                    'details': bet_data
                })
                result = {
                    "success": True,
                    "message": f"Bet on {bet_data.get('home_team')} vs {bet_data.get('away_team')} ({bet_data.get('outcome_name')} @ {bet_data.get('odds')}) added to ticket.",
                    "data": {"current_ticket_bets": flow_context['bets_in_progress']}
                }
            else:
                result = {"success": False, "message": "Failed to retrieve bet details.", "data": {}}

        elif action_type == 'parse_and_confirm_ticket':
            if not raw_bet_string:
                return {"success": False, "message": "No betting information was provided.", "data": {"bet_parsing_status": False, "bet_parsing_message": "No betting information was provided."}}

            # 1. Parse the raw text string into bets and stake
            parsed_data = parse_betting_string(raw_bet_string)
            if not parsed_data.get("success"):
                return {"success": False, "message": parsed_data.get("message", "Could not understand your bet."), "data": {"bet_parsing_status": False, "bet_parsing_message": parsed_data.get("message", "Could not understand your bet.")}}

            market_outcome_ids = parsed_data.get("market_outcome_ids", [])
            stake = parsed_data.get("stake", 0.0)

            # 2. Fetch outcomes and calculate total odds
            try:
                # Ensure IDs are integers for the query
                int_market_outcome_ids = [int(i) for i in market_outcome_ids]
                outcomes = MarketOutcome.objects.filter(id__in=int_market_outcome_ids).select_related('market__fixture__home_team', 'market__fixture__away_team')
                
                if len(outcomes) != len(market_outcome_ids):
                    return {"success": False, "message": "One or more of your selections are invalid or no longer available.", "data": {"bet_parsing_status": False, "bet_parsing_message": "One or more of your selections are invalid or no longer available."}}

                total_odds = Decimal('1.0')
                selections_text_list = []
                for outcome in outcomes:
                    total_odds *= outcome.odds
                    selections_text_list.append(
                        f"  - {outcome.market.fixture.home_team.name} vs {outcome.market.fixture.away_team.name}\n"
                        f"    Selection: {outcome.outcome_name} @ {outcome.odds:.2f}"
                    )
                
                potential_winnings = Decimal(stake) * total_odds
                
                # 3. Format the confirmation message
                confirmation_message = "*Please confirm your bet:*\n\n"
                confirmation_message += "*Selections:*\n"
                confirmation_message += "\n\n".join(selections_text_list)
                confirmation_message += f"\n\n*Total Stake:* ${stake:.2f}"
                confirmation_message += f"\n*Potential Winnings:* ${potential_winnings:.2f}"

                # 4. Prepare data for context
                data_for_context = {
                    "bet_parsing_status": True,
                    "bet_confirmation_message": confirmation_message,
                    "parsed_bet_data": { # Store the validated data needed for placement
                        "market_outcome_ids": market_outcome_ids,
                        "stake": stake,
                    }
                }
                return {"success": True, "message": "Bet parsed successfully.", "data": data_for_context}

            except Exception as e:
                logger.error(f"Error during bet parsing/confirmation for contact {contact.whatsapp_id}: {e}", exc_info=True)
                return {"success": False, "message": "An internal error occurred while preparing your bet.", "data": {"bet_parsing_status": False, "bet_parsing_message": "An internal error occurred while preparing your bet."}}

        elif action_type == 'place_ticket_from_context':
            parsed_bet_data = flow_context.get('parsed_bet_data')
            if not parsed_bet_data or not isinstance(parsed_bet_data, dict):
                return {"success": False, "message": "Could not find your bet details to place the ticket. Please start over.", "data": {"place_ticket_status": False, "place_ticket_message": "Could not find your bet details to place the ticket. Please start over."}}

            market_outcome_ids = parsed_bet_data.get("market_outcome_ids")
            stake = parsed_bet_data.get("stake")

            if not market_outcome_ids or not stake:
                return {"success": False, "message": "Your bet details are incomplete. Please start over.", "data": {"place_ticket_status": False, "place_ticket_message": "Your bet details are incomplete. Please start over."}}

            # Call the existing ticket processing logic
            place_result = process_bet_ticket_submission(
                whatsapp_id=contact.whatsapp_id,
                market_outcome_ids=market_outcome_ids,
                stake=stake
            )
            
            # Adapt the result to what the flow expects
            final_result_data = {
                "place_ticket_status": place_result.get("success", False),
                "place_ticket_message": place_result.get("message", "An unknown error occurred."),
            }
            if place_result.get("success"):
                final_result_data["ticket_id"] = place_result.get("ticket_id")
                final_result_data["new_balance"] = place_result.get("new_balance")

            return {"success": place_result.get("success"), "message": place_result.get("message"), "data": final_result_data}

        elif action_type == 'view_single_ticket':
            if not ticket_id:
                return {"success": False, "message": "Ticket ID is required to view a specific ticket.", "data": {"single_ticket_status": False, "single_ticket_message": "Ticket ID is required."}}
            
            try:
                # Ensure ticket_id is an integer
                ticket_id_int = int(ticket_id)
                ticket = BetTicket.objects.filter(user=customer_profile.user, id=ticket_id_int).prefetch_related(
                    'bets__market_outcome__market__fixture__home_team',
                    'bets__market_outcome__market__fixture__away_team',
                    'bets__market_outcome__market__category'
                ).first()

                if not ticket:
                    return {"success": False, "message": f"Ticket ID {ticket_id} not found or does not belong to you.", "data": {"single_ticket_status": False, "single_ticket_message": f"Ticket ID {ticket_id} not found or does not belong to you."}}
                
                # Format the detailed ticket information
                ticket_message = f"🎫 *Ticket ID: {ticket.id}*\n"
                ticket_message += f"Status: {ticket.get_status_display()}\n"
                ticket_message += f"Total Stake: ${float(ticket.total_stake):.2f}\n"
                ticket_message += f"Potential Winnings: ${float(ticket.potential_winnings):.2f}\n"
                ticket_message += f"Placed On: {timezone.localtime(ticket.created_at).strftime('%Y-%m-%d %H:%M')}\n\n"
                
                ticket_message += "*Individual Bets:*\n"
                for bet in ticket.bets.all():
                    fixture_name = f"{bet.market_outcome.market.fixture.home_team.name} vs {bet.market_outcome.market.fixture.away_team.name}"
                    ticket_message += f"  - Match: {fixture_name}\n"
                    ticket_message += f"    Selection: {bet.market_outcome.outcome_name} ({bet.market_outcome.market.category.name})\n"
                    ticket_message += f"    Odds: {float(bet.market_outcome.odds):.2f}\n"
                    ticket_message += f"    Bet Status: {bet.get_status_display()}\n"
                    ticket_message += "    ---\n"
                
                return {"success": True, "message": "Ticket details retrieved.", "data": {"single_ticket_status": True, "single_ticket_message": ticket_message}}
            except ValueError:
                return {"success": False, "message": "Invalid Ticket ID format. Please enter a number.", "data": {"single_ticket_status": False, "single_ticket_message": "Invalid Ticket ID format. Please enter a number."}}
            except Exception as e:
                logger.error(f"Error viewing single ticket for contact {contact.whatsapp_id}, ticket ID {ticket_id}: {e}", exc_info=True)
                return {"success": False, "message": "An unexpected error occurred while fetching ticket details.", "data": {"single_ticket_status": False, "single_ticket_message": "An unexpected error occurred while fetching ticket details."}}

        elif action_type == 'view_my_tickets': # This action is no longer directly used in the flow, but kept for completeness
            tickets = BetTicket.objects.filter(user=customer_profile.user).order_by('-created_at')
            
            from football_data_app.utils import MAX_CHARS_PER_MESSAGE_PART, MESSAGE_PART_SEPARATOR

            MAX_CHARS_PER_PART_ACTION = MAX_CHARS_PER_MESSAGE_PART
            ITEM_SEPARATOR_ACTION = MESSAGE_PART_SEPARATOR # Separator between tickets in a part
            now_harare = timezone.localtime(timezone.now())
            datetime_str = now_harare.strftime('%B %d, %Y, %I:%M %p %Z')
            footer_string = f"\n\n_Generated by BetBlitz on {datetime_str}_"

            if not tickets:
                message_parts = ["You have no betting tickets yet." + footer_string]
            else:
                ticket_detail_strings = [
                    f"Ticket ID: {t.id}\nStatus: {t.get_status_display()}\nStake: ${float(t.total_stake):.2f}\nPotential Winnings: ${float(t.potential_winnings):.2f}"
                    for t in tickets
                ]

                all_message_parts: List[str] = []
                current_part_buffer: List[str] = []
                current_part_length = 0
                
                list_header = "Your betting tickets:"
                header_allowance_tickets = len(list_header) + len("\n") # Header + newline

                for i, ticket_str in enumerate(ticket_detail_strings):
                    separator_len = len(ITEM_SEPARATOR_ACTION) if current_part_buffer else 0
                    
                    prospective_item_len = separator_len + len(ticket_str)
                    current_total_prospective_len = current_part_length + prospective_item_len

                    if not all_message_parts: # Potentially the first part
                        current_total_prospective_len += header_allowance_tickets

                    if current_total_prospective_len > MAX_CHARS_PER_PART_ACTION and current_part_buffer:
                        part_to_add = ITEM_SEPARATOR_ACTION.join(current_part_buffer)
                        if not all_message_parts: # This was the first part, prepend header
                            part_to_add = list_header + "\n" + part_to_add
                        all_message_parts.append(part_to_add)
                        
                        current_part_buffer = [ticket_str]
                        current_part_length = len(ticket_str)
                    else:
                        current_part_buffer.append(ticket_str)
                        current_part_length += prospective_item_len

                if current_part_buffer:
                    final_part_str = ITEM_SEPARATOR_ACTION.join(current_part_buffer)
                    if not all_message_parts: # First and only part
                        final_part_str = list_header + "\n" + final_part_str
                    all_message_parts.append(final_part_str)
                
                message_parts = all_message_parts

                if message_parts: # Add footer to the last part
                    if len(message_parts[-1]) + len(footer_string) <= MAX_CHARS_PER_PART_ACTION:
                        message_parts[-1] += footer_string
                    else:
                        message_parts.append(footer_string)

            result = {
                "success": True,
                "message": message_parts, # List of strings
                "data": {"tickets_parts": message_parts}
            }

        elif action_type == 'check_wallet_balance':
            balance_info = get_customer_wallet_balance(contact.whatsapp_id)
            result = {
                "success": balance_info.get('success'),
                "message": f"Your current wallet balance is: ${balance_info.get('balance', 0.0):.2f}" if balance_info.get('success') else balance_info.get('message'),
                "data": {"balance": balance_info.get('balance')}
            }

        else:
            result = {"success": False, "message": f"Unsupported betting action: {action_type}", "data": {}}
    except Exception as e:
        import traceback
        traceback.print_exc()
        result = {"success": False, "message": f"An error occurred: {str(e)}", "data": {}}

    return result
