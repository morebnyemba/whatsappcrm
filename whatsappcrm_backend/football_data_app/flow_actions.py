# whatsappcrm_backend/football_data_app/flow_actions.py
import logging
from typing import Optional
from django.utils import timezone
from datetime import timedelta, datetime # Ensure datetime is imported
from .models import FootballFixture

logger = logging.getLogger(__name__)

def format_matches_for_display(matches_qs, data_type_label: str, league_code: str):
    if not matches_qs.exists():
        return f"No {data_type_label.lower().replace('_', ' ')} found for {league_code}."

    message_lines = [f"⚽ {data_type_label.replace('_', ' ').capitalize()} for {league_code}:"]
    for match in matches_qs[:10]: # Limit to 10 for display
        match_time_local = timezone.localtime(match.match_datetime_utc)
        line = f"\n🗓️ {match_time_local.strftime('%a, %b %d - %I:%M %p %Z')}\n"
        line += f"{match.home_team_name} vs {match.away_team_name}"
        if match.status == 'FINISHED' and match.home_score is not None and match.away_score is not None:
            line += f"\n🏁 Result: {match.home_score} - {match.away_score}"
            if match.winner:
                winner_name = match.home_team_name if match.winner == 'HOME_TEAM' else match.away_team_name if match.winner == 'AWAY_TEAM' else 'Draw'
                line += f" ({winner_name} won)" if match.winner != 'DRAW' else " (Draw)"
        message_lines.append(line)
    return "\n\n".join(message_lines)

def get_formatted_football_data(
    league_code: Optional[str], 
    data_type: str, 
    days_ahead: int = 7, 
    days_past: int = 2
):
    logger.info(f"Getting formatted football data for league '{league_code}', type '{data_type}'")

    if not league_code or league_code.upper() == 'ALL': # Handle "ALL" or missing league code
        # If ALL, you might want to fetch for a few popular ones or say "please specify"
        # For now, let's default to BSA if ALL or empty, or indicate need for specification
        if league_code and league_code.upper() == 'ALL':
             # Potentially fetch for multiple or a default set - simplified here
            logger.warning("Fetching 'ALL' leagues is not fully implemented in this example, defaulting to BSA or a generic message.")
            league_code = 'BSA' # Default for now
        elif not league_code:
             return "Please specify a league or choose from the list."

    league_code = league_code.upper().replace("LEAGUE_", "") # Clean up ID from interactive reply

    if data_type == "scheduled_fixtures":
        start_date = timezone.now()
        end_date = start_date + timedelta(days=days_ahead)
        fixtures_qs = FootballFixture.objects.filter(
            competition_code=league_code,
            status='SCHEDULED',
            match_datetime_utc__gte=start_date,
            match_datetime_utc__lte=end_date
        ).order_by('match_datetime_utc')
        return format_matches_for_display(fixtures_qs, "Scheduled Fixtures", league_code)

    elif data_type == "finished_results":
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days_past)
        fixtures_qs = FootballFixture.objects.filter(
            competition_code=league_code,
            status='FINISHED',
            match_datetime_utc__gte=start_date,
            match_datetime_utc__lte=end_date
        ).order_by('-match_datetime_utc')
        return format_matches_for_display(fixtures_qs, "Finished Results", league_code)

    return "Invalid data type requested."