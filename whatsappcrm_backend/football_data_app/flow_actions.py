import logging
from typing import Optional, Dict, List # Added List for type hinting
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal 

from .models import FootballFixture, MarketOutcome, Market, League

logger = logging.getLogger(__name__)

# --- Configuration for Message Splitting ---
WHATSAPP_CHAR_LIMIT = 4000 # Using a slightly conservative limit (WhatsApp is 4096)
MESSAGE_SEPARATOR = "\n\n---\n" # Separator between individual match/result blocks


def get_formatted_football_data(
    data_type: str, 
    league_code: Optional[str] = None, 
    days_ahead: int = 5,  # Changed default back to 10 days
    days_past: int = 2
) -> List[str]: # Return type remains List[str] for multi-message support
    """
    Fetches and formats football data for display.
    Supports 'scheduled_fixtures' (upcoming matches) and 'finished_results' (recent scores).
    Output is highly condensed: League, Match ID, Teams, and simplified odds/results.
    Generates a list of strings, each formatted to fit within WhatsApp's message size limit.
    """
    logger.info(f"Function Call: get_formatted_football_data(data_type='{data_type}', league_code='{league_code}', days_ahead={days_ahead}, days_past={days_past})")

    now = timezone.now()
    all_formatted_items: List[str] = [] # Stores individual formatted match/result blocks
    main_header = "" # To be set based on data_type
    
    if data_type == "scheduled_fixtures":
        main_header = "⚽ *Upcoming Matches*"
        data_type_label = "Upcoming Matches" # For log messages
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
            return [f"No {data_type_label.lower()} found{league_info} at this time."] # Return list with single message

        # Loop through fixtures and format each one individually
        logger.debug(f"Preparing individual formatted blocks for scheduled matches.")
        for match in fixtures_qs: # Process all matches first, then split
            # Removed match_time_local and time_str as date/time is no longer displayed
            
            # Simplified line output for scheduled matches
            line = f"*{match.league.name}*\n" # League name
            line += f"ID: {match.id} | {match.home_team.name} vs {match.away_team.name}\n"
            
            # --- Aggregate and select best odds for display (one per odd type) ---
            aggregated_outcomes: Dict[str, Dict[str, MarketOutcome]] = {} 
            
            for market in match.markets.all():
                market_key = market.api_market_key
                if market_key not in aggregated_outcomes:
                    aggregated_outcomes[market_key] = {}

                for outcome in market.outcomes.all():
                    outcome_identifier = f"{outcome.outcome_name}-{outcome.point_value if outcome.point_value is not None else ''}"
                    current_best_outcome = aggregated_outcomes[market_key].get(outcome_identifier)
                    if current_best_outcome is None or outcome.odds > current_best_outcome.odds:
                        aggregated_outcomes[market_key][outcome_identifier] = outcome
            
            # --- Prepare display lines based on desired simplification (one per type) ---
            display_odds_found = False
            compact_odds_parts: List[str] = [] # Use this to build a single line for odds

            # H2H (Moneyline) - Home | Draw | Away
            if 'h2h' in aggregated_outcomes:
                home_odds = None; draw_odds = None; away_odds = None

                for identifier, outcome_obj in aggregated_outcomes['h2h'].items():
                    if outcome_obj.outcome_name == match.home_team.name: home_odds = outcome_obj
                    elif outcome_obj.outcome_name.lower() == 'draw': draw_odds = outcome_obj
                    elif outcome_obj.outcome_name == match.away_team.name: away_odds = outcome_obj
                
                # Append H2H to compact line
                if home_odds: compact_odds_parts.append(f"H:*{home_odds.odds}*")
                if draw_odds: compact_odds_parts.append(f"D:*{draw_odds.odds}*")
                if away_odds: compact_odds_parts.append(f"A:*{away_odds.odds}*")
                if home_odds or draw_odds or away_odds: display_odds_found = True

            # Totals (Over/Under) - Single best Over and single best Under
            if 'totals' in aggregated_outcomes:
                best_overall_over = None; best_overall_under = None

                for outcome_obj in aggregated_outcomes['totals'].values():
                    if 'over' in outcome_obj.outcome_name.lower():
                        if best_overall_over is None or outcome_obj.odds > best_overall_over.odds: best_overall_over = outcome_obj
                    elif 'under' in outcome_obj.outcome_name.lower():
                        if best_overall_under is None or outcome_obj.odds > best_overall_under.odds: best_overall_under = outcome_obj
                
                # Append Totals to compact line
                if best_overall_over: compact_odds_parts.append(f"O{best_overall_over.point_value if best_overall_over.point_value is not None else ''}:*{best_overall_over.odds}*")
                if best_overall_under: compact_odds_parts.append(f"U{best_overall_under.point_value if best_overall_under.point_value is not None else ''}:*{best_overall_under.odds}*")
                if best_overall_over or best_overall_under: display_odds_found = True

            # BTTS (Both Teams To Score) - Yes | No
            if 'btts' in aggregated_outcomes:
                yes_odds = aggregated_outcomes['btts'].get('Yes-') 
                no_odds = aggregated_outcomes['btts'].get('No-')   

                if yes_odds: compact_odds_parts.append(f"BTTS Y:*{yes_odds.odds}*")
                if no_odds: compact_odds_parts.append(f"BTTS N:*{no_odds.odds}*")
                if yes_odds or no_odds: display_odds_found = True
            
            # Spreads (Handicap) - Single best Home Spread and single best Away Spread
            if 'spreads' in aggregated_outcomes:
                best_home_spread = None; best_away_spread = None

                for outcome_obj in aggregated_outcomes['spreads'].values():
                    if outcome_obj.outcome_name == match.home_team.name:
                        if best_home_spread is None or outcome_obj.odds > best_home_spread.odds: best_home_spread = outcome_obj
                    elif outcome_obj.outcome_name == match.away_team.name:
                        if best_away_spread is None or outcome_obj.odds > best_away_spread.odds: best_away_spread = outcome_obj
                
                if best_home_spread: compact_odds_parts.append(f"S {match.home_team.name}({best_home_spread.point_value}):*{best_home_spread.odds}*")
                if best_away_spread: compact_odds_parts.append(f"S {match.away_team.name}({best_away_spread.point_value}):*{best_away_spread.odds}*")
                if best_home_spread or best_away_spread: display_odds_found = True

            # --- Final odds output assembly for this match ---
            if display_odds_found:
                line += "Odds: " + " | ".join(compact_odds_parts)
            else:
                line += "Odds: No odds." # Compact message if no odds
            
            all_formatted_items.append(line)
        
    elif data_type == "finished_results":
        main_header = "⚽ *Recent Results*"
        data_type_label = "Recent Results" # For log messages
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
            return [f"No {data_type_label.lower()} found{league_info} at this time."] # Return list with single message

        # Loop through fixtures and format each one individually
        logger.debug(f"Preparing individual formatted blocks for finished results.")
        for match in fixtures_qs: # Process all matches first, then split
            # Removed match_time_local and time_str as date/time is no longer displayed
            
            # Simplified line output for finished results
            line = f"*{match.league.name}*\n" # League name
            line += f"ID: {match.id} | {match.home_team.name} vs {match.away_team.name}"
            
            if match.home_team_score is not None:
                line += f" | Result: {match.home_team_score} - {match.away_team_score}" # Compact result
            # Removed else for _Scores not available_

            all_formatted_items.append(line)

    else:
        logger.warning(f"Invalid data type requested: '{data_type}'. Returning error message.")
        return ["Invalid data type requested. Please check your input."] # Return list with single error message

    # --- Split all_formatted_items into multiple messages ---
    final_messages: List[str] = []
    current_message_buffer: List[str] = []
    
    # Start with the main header in the first message part
    if all_formatted_items: # Only add header if there are items to send
        current_message_buffer.append(main_header)

    logger.debug(f"Starting message splitting process. Total items to split: {len(all_formatted_items)}.")
    for i, item in enumerate(all_formatted_items):
        # Calculate potential length if this item were added to the current buffer
        # Add a small buffer for the separator length if it's not the first item after header
        potential_length = len("\n".join(current_message_buffer)) + (len(MESSAGE_SEPARATOR) if len(current_message_buffer) > 1 else 0) + len(item)
        
        # If adding this item would exceed the limit, finalize the current message part
        if potential_length > WHATSAPP_CHAR_LIMIT and len(current_message_buffer) > 0:
            final_messages.append(MESSAGE_SEPARATOR.join(current_message_buffer)) # Join with separator
            logger.debug(f"Message part {len(final_messages)} finalized (length: {len(final_messages[-1])}). Starting new part.")
            current_message_buffer = [main_header] # Start new message part with header
            
            # Re-check the length for the new message part with the current item
            if len("\n".join(current_message_buffer) + MESSAGE_SEPARATOR + item) > WHATSAPP_CHAR_LIMIT:
                logger.warning(f"Single item (Match/Result {i+1}) is too long for WhatsApp limit even in a new message part. Skipping this item.")
                # If a single item is too long, we skip it. You might want to handle this differently (e.g., truncate, send as single long message if platform allows)
                current_message_buffer = [main_header] # Reset buffer for next item, effectively skipping current too-long item
                continue # Move to next item
            else:
                current_message_buffer.append(item)
        else:
            current_message_buffer.append(item)
            
    # Add any remaining content in the buffer to the final list of messages
    if current_message_buffer:
        final_messages.append(MESSAGE_SEPARATOR.join(current_message_buffer)) # Join with separator
        logger.debug(f"Last message part {len(final_messages)} finalized (length: {len(final_messages[-1])}).")

    if not final_messages: # In case no items were processed for some edge case
        return ["No data available to display."]

    logger.info(f"Successfully formatted data for data_type='{data_type}'. Generated {len(final_messages)} message parts.")
    return final_messages