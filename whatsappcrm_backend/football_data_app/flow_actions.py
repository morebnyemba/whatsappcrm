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
    Fetches and formats football data (fixtures or results) for display.
    This version uses the correct model fields and has improved logic.
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
        ).select_related('home_team', 'away_team', 'league').order_by('match_date')

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
        return "Invalid data type requested."

    # --- Formatting the Message ---
    
    if not fixtures_qs.exists():
        league_info = f" in {league_code}" if league_code else ""
        return f"No {data_type_label.lower()} found{league_info} at this time."

    message_lines = [f"⚽ *{data_type_label}*"]
    
    # Limit to 10 to keep the message from getting too long
    for match in fixtures_qs[:10]:
        # Format the match time to a user-friendly string
        match_time_local = timezone.localtime(match.match_date)
        time_str = match_time_local.strftime('%a, %b %d - %I:%M %p')

        line = f"\n*Match ID*: {match.id}\n"
        line += f"🗓️ {time_str}\n"
        line += f"{match.home_team.name} vs {match.away_team.name}"
        
        if match.status == 'FINISHED' and match.home_team_score is not None:
            line += f"\n🏁 *Result: {match.home_team_score} - {match.away_team_score}*"
            
        message_lines.append(line)
        
    return "\n\n---\n".join(message_lines)