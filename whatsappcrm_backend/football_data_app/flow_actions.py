import logging
from typing import Optional, Dict
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal 

from .models import FootballFixture, MarketOutcome, Market, League
from customer_data.models import Bet, BetTicket, Customer # Assuming Customer model is linked to BetTicket

logger = logging.getLogger(__name__)

def get_formatted_football_data(
    data_type: str, 
    league_code: Optional[str] = None, 
    days_ahead: int = 14, 
    days_past: int = 2,
    customer_id: Optional[int] = None # New parameter for customer-specific requests
) -> str:
    """
    Fetches and formats football data for display based on the requested data_type.
    Supports 'scheduled_fixtures' (upcoming matches), 'finished_results' (recent scores),
    and 'customer_tickets' (user's betting history).
    Includes extensive logging for robustness and clarity.
    """
    logger.info(f"Function Call: get_formatted_football_data(data_type='{data_type}', league_code='{league_code}', days_ahead={days_ahead}, days_past={days_past}, customer_id={customer_id})")

    now = timezone.now()
    message_lines = []
    
    if data_type == "scheduled_fixtures":
        data_type_label = "Upcoming Matches"
        start_date = now
        end_date = now + timedelta(days=days_ahead)
        
        logger.debug(f"Querying for SCHEDULED fixtures between {start_date} and {end_date}.")
        fixtures_qs = FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.SCHEDULED,
            match_date__gte=start_date,
            match_date__lte=end_date
        ).select_related('home_team', 'away_team', 'league').prefetch_related(
            'markets__outcomes'
        ).order_by('match_date')

        if league_code:
            logger.debug(f"Filtering scheduled fixtures by league_code: {league_code}.")
            fixtures_qs = fixtures_qs.filter(league__api_id=league_code)

        if not fixtures_qs.exists():
            league_info = f" in {league_code}" if league_code else ""
            logger.info(f"No {data_type_label.lower()} found{league_info} for the specified criteria.")
            return f"No {data_type_label.lower()} found{league_info} at this time."

        message_lines = [f"⚽ *{data_type_label}*"]
        
        # Limiting to 20 matches for brevity in chat responses
        logger.debug(f"Formatting details for up to {min(fixtures_qs.count(), 20)} scheduled matches.")
        for match in fixtures_qs[:20]: 
            match_time_local = timezone.localtime(match.match_date)
            time_str = match_time_local.strftime('%a, %b %d - %I:%M %p')

            line = f"\n*Match ID*: {match.id}\n"
            line += f"🗓️ {time_str}\n"
            line += f"🏆 *League*: {match.league.name}\n"
            line += f"*{match.home_team.name} vs {match.away_team.name}*"
            
            # --- Aggregate and select best odds for display ---
            aggregated_outcomes: Dict[str, Dict[str, MarketOutcome]] = {} 
            
            logger.debug(f"Aggregating odds for match {match.id}.")
            for market in match.markets.all():
                market_key = market.api_market_key
                if market_key not in aggregated_outcomes:
                    aggregated_outcomes[market_key] = {}

                for outcome in market.outcomes.all():
                    outcome_identifier = f"{outcome.outcome_name}-{outcome.point_value if outcome.point_value is not None else ''}"

                    current_best_outcome = aggregated_outcomes[market_key].get(outcome_identifier)
                    if current_best_outcome is None or outcome.odds > current_best_outcome.odds:
                        aggregated_outcomes[market_key][outcome_identifier] = outcome
            
            # --- Prepare display lines based on desired simplification ---
            display_odds_found = False
            display_market_lines = []

            # H2H (Moneyline) - Simplify to just Home, Draw, Away
            if 'h2h' in aggregated_outcomes:
                h2h_line_parts = []
                home_odds = None
                draw_odds = None
                away_odds = None

                for identifier, outcome_obj in aggregated_outcomes['h2h'].items():
                    if outcome_obj.outcome_name == match.home_team.name:
                        home_odds = outcome_obj
                    elif outcome_obj.outcome_name.lower() == 'draw':
                        draw_odds = outcome_obj
                    elif outcome_obj.outcome_name == match.away_team.name:
                        away_odds = outcome_obj
                
                if home_odds: h2h_line_parts.append(f"{match.home_team.name}: *{home_odds.odds}*")
                if draw_odds: h2h_line_parts.append(f"Draw: *{draw_odds.odds}*")
                if away_odds: h2h_line_parts.append(f"{match.away_team.name}: *{away_odds.odds}*")
                
                if h2h_line_parts:
                    display_market_lines.append("Head-to-Head: " + " | ".join(h2h_line_parts))
                    display_odds_found = True

            # Totals (Over/Under) - Display ALL available point values
            if 'totals' in aggregated_outcomes:
                total_outcomes_to_display = sorted(
                    aggregated_outcomes['totals'].values(),
                    key=lambda o: (o.point_value if o.point_value is not None else float('inf'), o.outcome_name)
                )
                
                if total_outcomes_to_display:
                    display_market_lines.append("Totals:")
                    for outcome_obj in total_outcomes_to_display:
                        point_str = f" {outcome_obj.point_value}" if outcome_obj.point_value is not None else ""
                        display_market_lines.append(f"  • {outcome_obj.outcome_name}{point_str}: *{outcome_obj.odds}*")
                    display_odds_found = True

            # BTTS (Both Teams To Score)
            if 'btts' in aggregated_outcomes:
                btts_line_parts = []
                yes_odds = aggregated_outcomes['btts'].get('Yes-') 
                no_odds = aggregated_outcomes['btts'].get('No-')   

                if yes_odds: btts_line_parts.append(f"Yes: *{yes_odds.odds}*")
                if no_odds: btts_line_parts.append(f"No: *{no_odds.odds}*")

                if btts_line_parts:
                    display_market_lines.append("BTTS: " + " | ".join(btts_line_parts))
                    display_odds_found = True
            
            # Spreads (Handicap)
            if 'spreads' in aggregated_outcomes:
                spread_outcomes_to_display = sorted(
                    aggregated_outcomes['spreads'].values(),
                    key=lambda o: (o.point_value if o.point_value is not None else float('-inf'), o.outcome_name)
                )
                if spread_outcomes_to_display:
                    display_market_lines.append("Spreads:")
                    for outcome_obj in spread_outcomes_to_display:
                        point_str = f" ({outcome_obj.point_value})" if outcome_obj.point_value is not None else ""
                        display_market_lines.append(f"  • {outcome_obj.outcome_name}{point_str}: *{outcome_obj.odds}*")
                    display_odds_found = True

            # --- Final odds output assembly ---
            if display_odds_found:
                line += f"\n\n- *Best Odds* -\n" + "\n".join(display_market_lines)
            else:
                if match.status == 'SCHEDULED':
                    line += "\n\n_Odds will be available soon._"

            message_lines.append(line)
        
    elif data_type == "finished_results":
        data_type_label = "Recent Results"
        end_date = now
        start_date = now - timedelta(days=days_past)
        
        logger.debug(f"Querying for FINISHED fixtures between {start_date} and {end_date}.")
        fixtures_qs = FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.FINISHED,
            match_date__gte=start_date,
            match_date__lte=end_date
        ).select_related('home_team', 'away_team', 'league').order_by('-match_date')
        
        if league_code:
            logger.debug(f"Filtering finished results by league_code: {league_code}.")
            fixtures_qs = fixtures_qs.filter(league__api_id=league_code)
        
        if not fixtures_qs.exists():
            league_info = f" in {league_code}" if league_code else ""
            logger.info(f"No {data_type_label.lower()} found{league_info} for the specified criteria.")
            return f"No {data_type_label.lower()} found{league_info} at this time."

        message_lines = [f"⚽ *{data_type_label}*"]
        
        logger.debug(f"Formatting details for up to {min(fixtures_qs.count(), 20)} finished matches.")
        for match in fixtures_qs[:20]: # Limiting to 20 matches
            match_time_local = timezone.localtime(match.match_date)
            time_str = match_time_local.strftime('%a, %b %d - %I:%M %p')

            line = f"\n*Match ID*: {match.id}\n"
            line += f"🗓️ {time_str}\n"
            line += f"🏆 *League*: {match.league.name}\n" # Added league name here
            line += f"*{match.home_team.name} vs {match.away_team.name}*\n"
            if match.home_team_score is not None:
                line += f"🏁 *Result: {match.home_team_score} - {match.away_team_score}*"
            else:
                line += "_Scores not available_"
            
            message_lines.append(line)

    elif data_type == "customer_tickets":
        data_type_label = "Your Bet Tickets"
        if customer_id is None:
            logger.warning("Request for customer_tickets without a customer_id. Returning error.")
            return "Please provide a customer ID to view bet tickets."

        try:
            customer = Customer.objects.get(id=customer_id)
            logger.info(f"Fetching bet tickets for customer ID: {customer_id} ({customer.name}).")
        except Customer.DoesNotExist:
            logger.warning(f"Customer with ID {customer_id} not found when requesting tickets.")
            return "Customer not found."
        except Exception as e:
            logger.exception(f"Unexpected error retrieving customer {customer_id} for ticket request.")
            return "An internal error occurred while fetching your tickets."

        # Fetch tickets for the customer, ordered by creation date, prefetching related data
        logger.debug(f"Querying for bet tickets for customer {customer.id}.")
        tickets_qs = BetTicket.objects.filter(
            customer=customer
        ).prefetch_related(
            'bets__market_outcome__market__fixture_display__home_team',
            'bets__market_outcome__market__fixture_display__away_team',
            'bets__market_outcome__market__fixture_display__league',
            'bets__market_outcome__market__bookmaker',
            'bets__market_outcome__market__category'
        ).order_by('-created_at')

        if not tickets_qs.exists():
            logger.info(f"No bet tickets found for customer ID: {customer_id}.")
            return f"No bet tickets found for {customer.name}."

        message_lines = [f"🎫 *{data_type_label}* for {customer.name}"]
        
        # Limit the number of tickets displayed (e.g., last 5 tickets)
        logger.debug(f"Formatting details for up to {min(tickets_qs.count(), 5)} customer tickets.")
        for ticket in tickets_qs[:5]: 
            ticket_line = f"\n*Ticket ID*: {ticket.id}\n"
            ticket_line += f"💰 *Total Stake*: ${ticket.total_stake:.2f}\n"
            ticket_line += f"📈 *Potential Payout*: ${ticket.potential_payout:.2f}\n"
            ticket_line += f"📊 *Status*: {ticket.status}\n"
            if ticket.settled_at:
                ticket_line += f"🗓️ *Settled*: {timezone.localtime(ticket.settled_at).strftime('%b %d, %I:%M %p')}\n"
            
            ticket_line += "\n*Bets on this Ticket*:\n"
            
            if not ticket.bets.exists():
                ticket_line += "  _No individual bets found for this ticket._\n"
                logger.warning(f"Ticket {ticket.id} has no associated bets.")

            for bet in ticket.bets.all():
                try:
                    outcome = bet.market_outcome
                    market = outcome.market
                    fixture = market.fixture_display
                    
                    bet_status = bet.status
                    # Format bet status for display
                    if bet_status == 'PENDING':
                        bet_status_display = "⏳ PENDING"
                    elif bet_status == 'WON':
                        bet_status_display = "✅ WON"
                    elif bet_status == 'LOST':
                        bet_status_display = "❌ LOST"
                    elif bet_status == 'PUSH':
                        bet_status_display = "➡️ PUSH"
                    else:
                        bet_status_display = bet_status.upper() # Fallback for other statuses

                    bet_detail_line = (
                        f"  • {fixture.home_team.name} vs {fixture.away_team.name} "
                        f"({fixture.league.name})\n"
                        f"    - Market: {market.category.name} ({market.bookmaker.name})\n"
                        f"    - Pick: {outcome.outcome_name}"
                    )
                    if outcome.point_value is not None:
                        bet_detail_line += f" {outcome.point_value}"
                    bet_detail_line += f": *{outcome.odds}* (Status: {bet_status_display})"
                    
                    ticket_line += f"{bet_detail_line}\n"
                    logger.debug(f"Added bet {bet.id} detail to ticket {ticket.id} output.")
                except AttributeError as e:
                    logger.error(f"Missing related data for bet {bet.id} on ticket {ticket.id}: {e}. Skipping bet detail.")
                    ticket_line += f"  • _Invalid bet data (Bet ID: {bet.id}) - Data missing._\n"
                except Exception as e:
                    logger.exception(f"Unexpected error processing bet {bet.id} for ticket {ticket.id}.")
                    ticket_line += f"  • _Error retrieving bet data (Bet ID: {bet.id}) - See logs._\n"

            message_lines.append(ticket_line)

    else:
        logger.warning(f"Invalid data type requested: '{data_type}'. Returning error message.")
        return "Invalid data type requested. Please check your input."

    # Final assembly of the message
    final_message = "\n\n---\n".join(message_lines)
    logger.info(f"Successfully formatted data for data_type='{data_type}'. Generated message length: {len(final_message)} characters.")
    return final_message