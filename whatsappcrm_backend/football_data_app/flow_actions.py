# whatsappcrm_backend/football_data_app/flow_actions.py
import logging
from typing import Optional, Dict
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal 

from .models import FootballFixture, MarketOutcome

logger = logging.getLogger(__name__)

def get_formatted_football_data(
    data_type: str, 
    league_code: Optional[str] = None, 
    days_ahead: int = 14, 
    days_past: int = 2
):
    """
    Fetches and formats football data for display.
    This version aggregates odds from all bookmakers and presents a clean, simple list.
    Includes league name for each match and increased days_ahead.
    Optimized to show only a single, most relevant odd value for H2H, but multiple for Totals.
    """
    logger.info(f"Getting formatted football data. Type: '{data_type}', League Code: '{league_code}', Days Ahead: {days_ahead}, Days Past: {days_past}")

    now = timezone.now()
    
    if data_type == "scheduled_fixtures":
        data_type_label = "Upcoming Matches"
        start_date = now
        end_date = now + timedelta(days=days_ahead)
        
        fixtures_qs = FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.SCHEDULED,
            match_date__gte=start_date,
            match_date__lte=end_date
        ).select_related('home_team', 'away_team', 'league').prefetch_related(
            'markets__outcomes'
        ).order_by('match_date')

        if league_code:
            fixtures_qs = fixtures_qs.filter(league__api_id=league_code)

    elif data_type == "finished_results":
        data_type_label = "Recent Results"
        end_date = now
        start_date = now - timedelta(days=days_past)
        fixtures_qs = FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.FINISHED,
            match_date__gte=start_date,
            match_date__lte=end_date
        ).select_related('home_team', 'away_team', 'league').order_by('-match_date')
        if league_code:
            fixtures_qs = fixtures_qs.filter(league__api_id=league_code)
    
    else:
        logger.warning(f"Invalid data type requested: {data_type}.")
        return "Invalid data type requested."

    ---
    
    If not fixtures_qs.exists():
        league_info = f" in {league_code}" if league_code else ""
        logger.info(f"No {data_type_label.lower()} found{league_info}.")
        return f"No {data_type_label.lower()} found{league_info} at this time."

    message_lines = [f"⚽ *{data_type_label}*"]
    
    # Limiting to 10 matches for brevity in chat responses
    for match in fixtures_qs[:10]: 
        match_time_local = timezone.localtime(match.match_date)
        time_str = match_time_local.strftime('%a, %b %d - %I:%M %p')

        line = f"\n*Match ID*: {match.id}\n"
        line += f"🗓️ {time_str}\n"
        line += f"🏆 *League*: {match.league.name}\n"
        line += f"*{match.home_team.name} vs {match.away_team.name}*"
        
        if match.status == 'FINISHED' and match.home_team_score is not None:
            line += f"\n🏁 *Result: {match.home_team_score} - {match.away_team_score}*"
        
        # --- Aggregate and select best odds for display ---
        # This dict will store the BEST odds for each unique outcome across ALL bookmakers.
        # For totals/spreads, it will store the best odds for each point value.
        aggregated_outcomes: Dict[str, Dict[str, MarketOutcome]] = {} 
        
        for market in match.markets.all():
            market_key = market.api_market_key
            if market_key not in aggregated_outcomes:
                aggregated_outcomes[market_key] = {}

            for outcome in market.outcomes.all():
                # For H2H, BTTS, Double Chance, the outcome_name is unique.
                # For Totals/Spreads, the combination of outcome_name and point_value is unique.
                outcome_identifier = f"{outcome.outcome_name}-{outcome.point_value if outcome.point_value is not None else ''}"

                current_best_outcome = aggregated_outcomes[market_key].get(outcome_identifier)
                # Store the outcome with the highest price (best odds)
                if current_best_outcome is None or outcome.odds > current_best_outcome.odds:
                    aggregated_outcomes[market_key][outcome_identifier] = outcome
        
        # --- Prepare display lines based on desired simplification ---
        display_odds_found = False
        display_lines = []

        # H2H (Moneyline) - Simplify to just Home, Draw, Away
        if 'h2h' in aggregated_outcomes:
            h2h_line_parts = []
            home_odds = None
            draw_odds = None
            away_odds = None

            # Find the best odds for each of the three H2H outcomes
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
                display_lines.append("Head-to-Head: " + " | ".join(h2h_line_parts))
                display_odds_found = True

        # Totals (Over/Under) - Display ALL available point values
        if 'totals' in aggregated_outcomes:
            # Collect all Over and Under outcomes, then sort by point value
            total_outcomes_to_display = sorted(
                aggregated_outcomes['totals'].values(),
                key=lambda o: (o.point_value if o.point_value is not None else float('inf'), o.outcome_name)
            )
            
            if total_outcomes_to_display:
                display_lines.append("Totals:")
                for outcome_obj in total_outcomes_to_display:
                    point_str = f" {outcome_obj.point_value}" if outcome_obj.point_value is not None else ""
                    display_lines.append(f"  • {outcome_obj.outcome_name}{point_str}: *{outcome_obj.odds}*")
                display_odds_found = True

        # BTTS (Both Teams To Score)
        if 'btts' in aggregated_outcomes:
            btts_line_parts = []
            yes_odds = aggregated_outcomes['btts'].get('Yes-') # Identifier for 'Yes' outcome
            no_odds = aggregated_outcomes['btts'].get('No-')   # Identifier for 'No' outcome

            if yes_odds: btts_line_parts.append(f"Yes: *{yes_odds.odds}*")
            if no_odds: btts_line_parts.append(f"No: *{no_odds.odds}*")

            if btts_line_parts:
                display_lines.append("BTTS: " + " | ".join(btts_line_parts))
                display_odds_found = True
        
        # Spreads (Handicap)
        if 'spreads' in aggregated_outcomes:
            # Display all available spread lines. Similar to totals.
            spread_outcomes_to_display = sorted(
                aggregated_outcomes['spreads'].values(),
                key=lambda o: (o.point_value if o.point_value is not None else float('-inf'), o.outcome_name)
            )
            if spread_outcomes_to_display:
                display_lines.append("Spreads:")
                for outcome_obj in spread_outcomes_to_display:
                    point_str = f" ({outcome_obj.point_value})" if outcome_obj.point_value is not None else ""
                    display_lines.append(f"  • {outcome_obj.outcome_name}{point_str}: *{outcome_obj.odds}*")
                display_odds_found = True

        # --- Final output assembly ---
        if display_odds_found:
            line += f"\n\n- *Best Odds* -\n" + "\n".join(display_lines)
        else:
            if match.status == 'SCHEDULED':
                line += "\n\n_Odds will be available soon._"

        message_lines.append(line)
        
    return "\n\n---\n".join(message_lines)