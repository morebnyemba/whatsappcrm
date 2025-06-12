import logging
from typing import Optional, Dict
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal 

from .models import FootballFixture, MarketOutcome, Market, League
# Removed imports for Customer, Bet, BetTicket as customer_tickets functionality is removed

logger = logging.getLogger(__name__)

def get_formatted_football_data(
    data_type: str, 
    league_code: Optional[str] = None, 
    days_ahead: int = 14, 
    days_past: int = 2
    # Removed customer_id parameter as customer_tickets functionality is removed
) -> str:
    """
    Fetches and formats football data for display.
    Supports 'scheduled_fixtures' (upcoming matches) and 'finished_results' (recent scores).
    Odds for scheduled fixtures are displayed one per odd type (e.g., single best Over/Under line).
    Includes extensive logging for robustness and clarity.
    """
    logger.info(f"Function Call: get_formatted_football_data(data_type='{data_type}', league_code='{league_code}', days_ahead={days_ahead}, days_past={days_past})")

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
            
            # --- Aggregate and select best odds for display (one per odd type) ---
            # This dict will store the BEST odds for each unique outcome across ALL bookmakers.
            # Example: {'h2h': {'Home Team Name-': OutcomeObj, 'Draw-': OutcomeObj}, 'totals': {'Over-2.5': OutcomeObj, 'Under-2.5': OutcomeObj}}
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
            
            # --- Prepare display lines based on desired simplification (one per type) ---
            display_odds_found = False
            display_market_lines = []

            # H2H (Moneyline) - Home | Draw | Away
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

            # Totals (Over/Under) - Single best Over and single best Under
            if 'totals' in aggregated_outcomes:
                best_overall_over = None
                best_overall_under = None

                for outcome_obj in aggregated_outcomes['totals'].values():
                    if 'over' in outcome_obj.outcome_name.lower():
                        if best_overall_over is None or outcome_obj.odds > best_overall_over.odds:
                            best_overall_over = outcome_obj
                    elif 'under' in outcome_obj.outcome_name.lower():
                        if best_overall_under is None or outcome_obj.odds > best_overall_under.odds:
                            best_overall_under = outcome_obj
                
                total_line_parts = []
                if best_overall_over:
                    total_line_parts.append(f"Over {best_overall_over.point_value if best_overall_over.point_value is not None else ''}: *{best_overall_over.odds}*")
                if best_overall_under:
                    total_line_parts.append(f"Under {best_overall_under.point_value if best_overall_under.point_value is not None else ''}: *{best_overall_under.odds}*")
                
                if total_line_parts:
                    display_market_lines.append("Totals: " + " | ".join(total_line_parts))
                    display_odds_found = True

            # BTTS (Both Teams To Score) - Yes | No
            if 'btts' in aggregated_outcomes:
                btts_line_parts = []
                yes_odds = aggregated_outcomes['btts'].get('Yes-') 
                no_odds = aggregated_outcomes['btts'].get('No-')   

                if yes_odds: btts_line_parts.append(f"Yes: *{yes_odds.odds}*")
                if no_odds: btts_line_parts.append(f"No: *{no_odds.odds}*")

                if btts_line_parts:
                    display_market_lines.append("BTTS: " + " | ".join(btts_line_parts))
                    display_odds_found = True
            
            # Spreads (Handicap) - Single best Home Spread and single best Away Spread
            if 'spreads' in aggregated_outcomes:
                best_home_spread = None
                best_away_spread = None

                for outcome_obj in aggregated_outcomes['spreads'].values():
                    if outcome_obj.outcome_name == match.home_team.name:
                        if best_home_spread is None or outcome_obj.odds > best_home_spread.odds:
                            best_home_spread = outcome_obj
                    elif outcome_obj.outcome_name == match.away_team.name:
                        if best_away_spread is None or outcome_obj.odds > best_away_spread.odds:
                            best_away_spread = outcome_obj
                
                spread_line_parts = []
                if best_home_spread:
                    spread_line_parts.append(f"{match.home_team.name} ({best_home_spread.point_value}): *{best_home_spread.odds}*")
                if best_away_spread:
                    spread_line_parts.append(f"{match.away_team.name} ({best_away_spread.point_value}): *{best_away_spread.odds}*")
                
                if spread_line_parts:
                    display_market_lines.append("Spreads: " + " | ".join(spread_line_parts))
                    display_odds_found = True

            # --- Final odds output assembly ---
            if display_odds_found:
                line += f"\n\n- *Best Odds* -\n" + "\n".join([f" • {l}" for l in display_market_lines])
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
            line += f"🏆 *League*: {match.league.name}\n"
            line += f"*{match.home_team.name} vs {match.away_team.name}*\n"
            if match.home_team_score is not None:
                line += f"🏁 *Result: {match.home_team_score} - {match.away_team_score}*"
            else:
                line += "_Scores not available_"
            
            message_lines.append(line)

    else:
        logger.warning(f"Invalid data type requested: '{data_type}'. Returning error message.")
        return "Invalid data type requested. Please check your input."

    # Final assembly of the message
    final_message = "\n\n---\n".join(message_lines)
    logger.info(f"Successfully formatted data for data_type='{data_type}'. Generated message length: {len(final_message)} characters.")
    return final_message