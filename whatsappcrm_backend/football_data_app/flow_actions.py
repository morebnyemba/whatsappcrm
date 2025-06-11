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
    days_ahead: int = 7, 
    days_past: int = 2
):
    """
    Fetches and formats football data for display.
    This version aggregates odds from all bookmakers and presents a clean, simple list.
    """
    logger.info(f"Getting formatted football data. Type: '{data_type}', League Code: '{league_code}'")

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
        # This part remains unchanged as results don't show odds
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
        return "Invalid data type requested."

    # --- Formatting the Message ---
    
    if not fixtures_qs.exists():
        league_info = f" in {league_code}" if league_code else ""
        return f"No {data_type_label.lower()} found{league_info} at this time."

    message_lines = [f"⚽ *{data_type_label}*"]
    
    for match in fixtures_qs[:10]:
        match_time_local = timezone.localtime(match.match_date)
        time_str = match_time_local.strftime('%a, %b %d - %I:%M %p')

        line = f"\n*Match ID*: {match.id}\n"
        line += f"🗓️ {time_str}\n"
        line += f"*{match.home_team.name} vs {match.away_team.name}*"
        
        if match.status == 'FINISHED' and match.home_team_score is not None:
            line += f"\n🏁 *Result: {match.home_team_score} - {match.away_team_score}*"
        
        # --- NEW: Aggregate odds from all bookmakers ---
        all_outcomes = {}
        for market in match.markets.all():
            for outcome in market.outcomes.all():
                # Create a unique key for each outcome type (e.g., "Over 2.5", "Chelsea")
                outcome_key = f"{outcome.outcome_name}{outcome.point_value or ''}"
                # Store the best odds available for that outcome
                if outcome_key not in all_outcomes or outcome.odds > all_outcomes[outcome_key].odds:
                    all_outcomes[outcome_key] = outcome
        
        if all_outcomes:
            line += f"\n\n- *Available Odds* -"
            for _, best_outcome in sorted(all_outcomes.items()):
                point_str = f" {best_outcome.point_value}" if best_outcome.point_value is not None else ""
                line += f"\n    • {best_outcome.outcome_name}{point_str}: *{best_outcome.odds}*"
        else:
            if match.status == 'SCHEDULED':
                line += "\n\n_Odds will be available soon._"

        message_lines.append(line)
        
    return "\n\n---\n".join(message_lines)