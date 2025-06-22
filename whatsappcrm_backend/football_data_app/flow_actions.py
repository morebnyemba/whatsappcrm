# whatsappcrm_backend/football_data_app/flow_actions.py

from conversations.models import Contact
from customer_data.models import CustomerProfile, UserWallet
from customer_data.ticket_processing import process_bet_ticket_submission
# IMPORTANT: Using 'FootballFixture' as the main fixture model name
from .models import FootballFixture, MarketOutcome # Import FootballFixture directly
from .football_engine import FootballEngine # Retained for other specific engine operations if any
from .utils import get_formatted_football_data, parse_betting_string
from typing import Optional, List
from django.utils import timezone # For footer timestamp in view_my_tickets


def handle_football_betting_action(
    contact: Contact,
    action_type: str,
    flow_context: dict,
    stake: float = None,
    market_outcome_id: str = None,
    ticket_id: str = None,
    raw_bet_string: str = None,
    # Parameters for get_formatted_football_data
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
    engine = FootballEngine() # The engine does not take any arguments on initialization
    result = {"success": False, "message": "Unknown betting action.", "data": {}}

    try:
        customer_profile = CustomerProfile.objects.get(contact=contact)
        if not customer_profile.user:
            return {"success": False, "message": "No linked user account found for this contact. Cannot perform betting actions.", "data": {}}
        user_wallet = UserWallet.objects.get(user=customer_profile.user)

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
                # Direct lookup for outcome details based on its UUID
                outcome_obj = MarketOutcome.objects.select_related('market__fixture__home_team', 'market__fixture__away_team').get(uuid=market_outcome_id)
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


        elif action_type == 'place_ticket':
            parsed_data = {"success": False, "message": "No betting data provided."}
            if raw_bet_string:
                parsed_data = parse_betting_string(raw_bet_string)
            elif flow_context.get('bets_in_progress'):
                parsed_data['success'] = True
                parsed_data['market_outcome_ids'] = [str(b['market_outcome_id']) for b in flow_context['bets_in_progress']]
                if stake:
                    parsed_data['stake'] = stake
                else:
                    parsed_data['success'] = False
                    parsed_data['message'] = "Stake amount not found for ticket from context."

            if not parsed_data['success']:
                return {"success": False, "message": parsed_data['message'], "data": {}}

            market_outcome_ids_to_process = parsed_data['market_outcome_ids']
            stake_to_process = parsed_data['stake']

            if not market_outcome_ids_to_process:
                return {"success": False, "message": "No valid betting options found to place the ticket.", "data": {}}
            if not stake_to_process or stake_to_process <= 0:
                return {"success": False, "message": "A valid stake amount is required to place the ticket.", "data": {}}

            place_result = process_bet_ticket_submission(
                whatsapp_id=contact.whatsapp_id,
                market_outcome_ids=market_outcome_ids_to_process,
                stake=stake_to_process
            )

            if place_result['success']:
                flow_context.pop('current_ticket_id', None)
                flow_context.pop('bets_in_progress', None)
                result = {
                    "success": True,
                    "message": place_result['message'],
                    "data": {"ticket_id": place_result.get('ticket_id'), "new_balance": place_result.get('new_balance')}
                }
            else:
                result = {
                    "success": False,
                    "message": place_result['message'],
                    "data": {"balance": float(user_wallet.balance) if user_wallet else 0.0}
                }

        elif action_type == 'view_my_tickets':
            tickets = engine.get_user_tickets(customer_profile.user.id)
            
            MAX_CHARS_PER_PART_ACTION = 4000
            ITEM_SEPARATOR_ACTION = "\n---\n" # Separator between tickets in a part
            now_harare = timezone.localtime(timezone.now())
            datetime_str = now_harare.strftime('%B %d, %Y, %I:%M %p %Z')
            footer_string = f"\n\n_Generated by BetBlitz on {datetime_str}_"

            if not tickets:
                message_parts = ["You have no betting tickets yet." + footer_string]
            else:
                ticket_detail_strings = [
                    f"Ticket ID: {t.id}\nStatus: {t.status}\nStake: {float(t.total_stake):.2f}\nPotential Winnings: {float(t.potential_winnings):.2f}"
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
            result = {
                "success": True,
                "message": f"Your current wallet balance is: {float(user_wallet.balance):.2f}",
                "data": {"balance": float(user_wallet.balance)}
            }

        else:
            result = {"success": False, "message": f"Unsupported betting action: {action_type}", "data": {}}

    except Contact.DoesNotExist:
        result = {"success": False, "message": "Contact not found.", "data": {}}
    except CustomerProfile.DoesNotExist:
        result = {"success": False, "message": "Customer profile not found.", "data": {}}
    except UserWallet.DoesNotExist:
        result = {"success": False, "message": "User wallet not found.", "data": {}}
    except Exception as e:
        import traceback
        traceback.print_exc()
        result = {"success": False, "message": f"An error occurred: {str(e)}", "data": {}}

    return result