# whatsappcrm_backend/football_data_app/flow_actions.py
import logging
from typing import Optional
from django.utils import timezone
from datetime import timedelta

from .models import FootballFixture

logger = logging.getLogger(__name__)

def get_formatted_football_data(
    data_type: str, 
    league_code: Optional[str] = None, 
    days_ahead: int = 14, # Increased default to 14 days
    days_past: int = 2
):
    """
    Fetches and formats football data for display.
    This version aggregates odds from all bookmakers and presents a clean, simple list.
    Includes league name for each match and increased days_ahead.
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
        ).select_related('home_team', 'away_team', 'league').prefetch_related( # 'league' is already here, good.
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

    # --- Formatting the Message ---
    
    if not fixtures_qs.exists():
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
        line += f"🏆 *League*: {match.league.name}\n" # Added league name here
        line += f"*{match.home_team.name} vs {match.away_team.name}*"
        
        if match.status == 'FINISHED' and match.home_team_score is not None:
            line += f"\n🏁 *Result: {match.home_team_score} - {match.away_team_score}*"
        
        # --- NEW: Aggregate odds from all bookmakers ---
        all_outcomes = {}
        # Ensure 'markets' relationship is loaded and iterated safely
        for market in match.markets.all(): 
            for outcome in market.outcomes.all():
                # Create a unique key for each outcome type (e.g., "Over 2.5", "Chelsea")
                # Using market.api_market_key + outcome.outcome_name + point_value for robustness
                outcome_key = f"{market.api_market_key}-{outcome.outcome_name}-{outcome.point_value or ''}"
                # Store the best odds available for that outcome (highest price)
                if outcome_key not in all_outcomes or outcome.odds > all_outcomes[outcome_key].odds:
                    all_outcomes[outcome_key] = outcome
        
        if all_outcomes:
            line += f"\n\n- *Available Odds* -"
            # Sort outcomes for consistent display
            for _, best_outcome in sorted(all_outcomes.items(), key=lambda item: item[1].outcome_name):
                # Format point_value if it exists and is not an integer 0 (to avoid "Over 0")
                point_str = ""
                if best_outcome.point_value is not None:
                    # Check if it's an int and 0 or if it's explicitly part of the name
                    # Simplistic check to avoid printing '0' for H2H draws
                    if best_outcome.point_value != 0 or 'totals' in best_outcome.market.api_market_key or 'spreads' in best_outcome.market.api_market_key:
                        point_str = f" {best_outcome.point_value}"
                
                line += f"\n    • {best_outcome.outcome_name}{point_str}: *{best_outcome.odds}*"
        else:
            if match.status == 'SCHEDULED':
                line += "\n\n_Odds will be available soon._"

        message_lines.append(line)
        
    return "\n\n---\n".join(message_lines)