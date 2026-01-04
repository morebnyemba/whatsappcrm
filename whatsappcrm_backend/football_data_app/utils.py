# whatsappcrm_backend/football_data_app/utils.py

import re
import logging
from django.db import transaction
from django.db.models import Q, Prefetch
from django.apps import apps
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Any, Union

# NOTE: All model and task imports are now done inside the functions that use them.
# This is the standard and correct way to resolve circular dependencies in Django.

logger = logging.getLogger(__name__)

# Message formatting constants
MAX_CHARS_PER_MESSAGE_PART = 4000
MESSAGE_PART_SEPARATOR = "\n\n---\n"
MAX_SINGLE_FIXTURE_LENGTH = 3500  # Max length for individual fixture (leaves room for headers/separators)

# Display limits for betting options (configurable)
MAX_TOTALS_LINES_TO_DISPLAY = 3  # Maximum Over/Under lines to show per fixture
MAX_CORRECT_SCORES_TO_DISPLAY = 4  # Maximum correct score options to show per fixture

def _format_handicap_market(outcomes_dict: Dict, fixture, market_name: str) -> Optional[str]:
    """
    Helper function to format handicap markets (Asian Handicap variants).
    Returns formatted string or None if no outcomes.
    """
    # Local import for type hints
    from football_data_app.models import MarketOutcome
    
    if not outcomes_dict:
        return None
    
    # Group by point value
    handicap_by_point: Dict[float, Dict[str, MarketOutcome]] = {}
    for outcome in outcomes_dict.values():
        if outcome.point_value is not None:
            if outcome.point_value not in handicap_by_point:
                handicap_by_point[outcome.point_value] = {}
            # Identify home vs away handicap
            if fixture.home_team.name in outcome.outcome_name or 'Home' in outcome.outcome_name:
                handicap_by_point[outcome.point_value]['home'] = outcome
            elif fixture.away_team.name in outcome.outcome_name or 'Away' in outcome.outcome_name:
                handicap_by_point[outcome.point_value]['away'] = outcome
    
    if not handicap_by_point:
        return None
    
    # Show ALL handicap lines, sorted by point value
    sorted_points = sorted(handicap_by_point.keys(), key=lambda x: abs(x))
    hcp_parts = []
    for point in sorted_points:
        home_hcp = handicap_by_point[point].get('home')
        away_hcp = handicap_by_point[point].get('away')
        
        if home_hcp:
            sign = '+' if point >= 0 else ''
            hcp_parts.append(f"  - {fixture.home_team.name} ({sign}{point}): *{home_hcp.odds:.2f}* (ID: {home_hcp.id})")
        if away_hcp:
            opposite_line = -point
            sign = '+' if opposite_line >= 0 else ''
            hcp_parts.append(f"  - {fixture.away_team.name} ({sign}{opposite_line}): *{away_hcp.odds:.2f}* (ID: {away_hcp.id})")
    
    if hcp_parts:
        return f"\n*{market_name}:*\n" + "\n".join(hcp_parts)
    return None

def _format_totals_market(outcomes_dict: Dict, market_name: str, max_lines: int = 3) -> Optional[str]:
    """
    Helper function to format totals/over-under markets.
    Returns formatted string or None if no outcomes.
    """
    # Local import for type hints
    from football_data_app.models import MarketOutcome
    
    if not outcomes_dict:
        return None
    
    totals_by_point: Dict[float, Dict[str, MarketOutcome]] = {}
    for outcome in outcomes_dict.values():
        if outcome.point_value is not None:
            if outcome.point_value not in totals_by_point:
                totals_by_point[outcome.point_value] = {}
            if 'over' in outcome.outcome_name.lower():
                totals_by_point[outcome.point_value]['over'] = outcome
            elif 'under' in outcome.outcome_name.lower():
                totals_by_point[outcome.point_value]['under'] = outcome
    
    if not totals_by_point:
        return None
    
    sorted_points = sorted(totals_by_point.keys())
    totals_parts = []
    for point in sorted_points[:max_lines]:
        over_outcome = totals_by_point[point].get('over')
        under_outcome = totals_by_point[point].get('under')
        over_str = f"Over {point:.1f}: *{over_outcome.odds:.2f}* (ID: {over_outcome.id})" if over_outcome else ""
        under_str = f"Under {point:.1f}: *{under_outcome.odds:.2f}* (ID: {under_outcome.id})" if under_outcome else ""
        if over_str and under_str:
            totals_parts.append(f"  - {over_str}")
            totals_parts.append(f"  - {under_str}")
        elif over_str or under_str:
            totals_parts.append(f"  - {over_str or under_str}")
    
    if totals_parts:
        return f"\n*{market_name}:*\n" + "\n".join(totals_parts)
    return None

def get_formatted_football_data(
    data_type: str,
    league_code: Optional[str] = None,
    days_ahead: int = 10,
    days_past: int = 4
) -> Optional[List[str]]:
    """
    Fetches and formats football data for display.
    This function now returns a list of strings (message parts) OR None if no data is found.
    """
    # --- Local Import to Prevent Circular Dependency ---
    from football_data_app.models import FootballFixture, MarketOutcome, Market

    logger.info(f"Function Call: get_formatted_football_data(data_type='{data_type}', league_code='{league_code}', days_ahead={days_ahead}, days_past={days_past})")

    now = timezone.now()
    now_harare = timezone.localtime(now)
    datetime_str = now_harare.strftime('%B %d, %Y, %I:%M %p %Z')
    footer_string = f"\n\n_Generated by BetBlitz on {datetime_str}_"

    individual_item_strings: List[str] = []
    main_header = ""
    data_type_label = ""

    if data_type == "scheduled_fixtures":
        data_type_label = "Upcoming Matches"
        main_header = f"⚽ *{data_type_label}*"
        start_date = now
        end_date = now + timedelta(days=days_ahead)
        logger.debug(f"Querying for SCHEDULED fixtures between {start_date} and {end_date}.")
        fixtures_qs = FootballFixture.objects.filter(
            Q(status=FootballFixture.FixtureStatus.SCHEDULED, match_date__gte=start_date, match_date__lte=end_date) |
            Q(status=FootballFixture.FixtureStatus.LIVE)
        ).select_related('home_team', 'away_team', 'league').prefetch_related(
            Prefetch('markets', queryset=Market.objects.filter(is_active=True)),
            Prefetch('markets__outcomes', queryset=MarketOutcome.objects.filter(is_active=True))
        ).order_by('match_date')


        if league_code:
            logger.debug(f"Filtering scheduled fixtures by league_code: {league_code}.")
            fixtures_qs = fixtures_qs.filter(league__api_id=league_code)

        if not fixtures_qs.exists():
            league_info = f" in {league_code}" if league_code else ""
            logger.info(f"No {data_type_label.lower()} found{league_info} for the specified criteria. Returning None.")
            return None

        num_fixtures_to_display = 40
        logger.debug(f"Formatting details for up to {min(fixtures_qs.count(), num_fixtures_to_display)} fixtures (scheduled & live).")

        def format_match_time(fixture):
            if fixture.status == FootballFixture.FixtureStatus.LIVE:
                elapsed_time = timezone.now() - fixture.match_date
                minutes = int(elapsed_time.total_seconds() // 60)
                return f"LIVE ({minutes}')" # e.g., LIVE (45')
            else:
                match_time_local = timezone.localtime(fixture.match_date)
                return match_time_local.strftime('%a, %b %d - %I:%M %p')

        for fixture in fixtures_qs[:num_fixtures_to_display]:
            time_str = format_match_time(fixture)

            line = f"\n🏆 *{fixture.league.name}* (ID: {fixture.id})"
            line += f"\n🗓️ {time_str}"
            
            if fixture.status == FootballFixture.FixtureStatus.LIVE and fixture.home_team_score is not None:
                line += f"\n{fixture.home_team.name} *{fixture.home_team_score} - {fixture.away_team_score}* {fixture.away_team.name}"
            else:
                line += f"\n{fixture.home_team.name} vs {fixture.away_team.name}"

            aggregated_outcomes: Dict[str, Dict[str, MarketOutcome]] = {}
            markets_list = list(fixture.markets.all())
            
            # Count total outcomes from all markets (used for diagnostic logging)
            total_outcome_count = 0
            
            for market in markets_list:
                market_key = market.api_market_key
                if market_key not in aggregated_outcomes:
                    aggregated_outcomes[market_key] = {}
                outcomes_list = list(market.outcomes.all())
                total_outcome_count += len(outcomes_list)
                
                for outcome in outcomes_list:
                    outcome_identifier = f"{outcome.outcome_name}-{outcome.point_value if outcome.point_value is not None else ''}"
                    current_best_outcome = aggregated_outcomes[market_key].get(outcome_identifier)
                    if current_best_outcome is None or outcome.odds > current_best_outcome.odds:
                        aggregated_outcomes[market_key][outcome_identifier] = outcome
            
            # Enhanced debug logging
            if not aggregated_outcomes:
                markets_count = len(markets_list)
                if markets_count == 0:
                    logger.warning(f"SKIPPING Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) - NO active markets in database")
                else:
                    logger.warning(f"SKIPPING Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) - has {markets_count} active markets with {total_outcome_count} outcomes but no valid odds aggregated")
            else:
                logger.debug(f"Fixture {fixture.id} has {len(aggregated_outcomes)} market types with odds: {list(aggregated_outcomes.keys())}")

            market_lines: List[str] = []

            # 1. Format H2H (Match Winner / 1X2)
            if 'h2h' in aggregated_outcomes or '1x2' in aggregated_outcomes or 'match_winner' in aggregated_outcomes:
                # Try different possible keys for match winner market
                h2h_outcomes = (aggregated_outcomes.get('h2h') or 
                               aggregated_outcomes.get('1x2') or 
                               aggregated_outcomes.get('match_winner') or {})
                
                home_odds = h2h_outcomes.get(f"{fixture.home_team.name}-") or h2h_outcomes.get('Home-') or h2h_outcomes.get('1-')
                draw_odds = h2h_outcomes.get('Draw-') or h2h_outcomes.get('X-')
                away_odds = h2h_outcomes.get(f"{fixture.away_team.name}-") or h2h_outcomes.get('Away-') or h2h_outcomes.get('2-')
                
                h2h_parts = []
                if home_odds: h2h_parts.append(f"  - {fixture.home_team.name}: *{home_odds.odds:.2f}* (ID: {home_odds.id})")
                if draw_odds: h2h_parts.append(f"  - Draw: *{draw_odds.odds:.2f}* (ID: {draw_odds.id})")
                if away_odds: h2h_parts.append(f"  - {fixture.away_team.name}: *{away_odds.odds:.2f}* (ID: {away_odds.id})")
                
                if h2h_parts:
                    market_lines.append("\n*Match Winner (1X2):*\n" + "\n".join(h2h_parts))

            # 2. Format Double Chance
            if 'double_chance' in aggregated_outcomes or 'doublechance' in aggregated_outcomes:
                dc_outcomes = aggregated_outcomes.get('double_chance') or aggregated_outcomes.get('doublechance') or {}
                
                home_draw = dc_outcomes.get('Home/Draw-') or dc_outcomes.get('1X-')
                home_away = dc_outcomes.get('Home/Away-') or dc_outcomes.get('12-')
                draw_away = dc_outcomes.get('Draw/Away-') or dc_outcomes.get('X2-')
                
                dc_parts = []
                if home_draw: dc_parts.append(f"  - Home/Draw (1X): *{home_draw.odds:.2f}* (ID: {home_draw.id})")
                if home_away: dc_parts.append(f"  - Home/Away (12): *{home_away.odds:.2f}* (ID: {home_away.id})")
                if draw_away: dc_parts.append(f"  - Draw/Away (X2): *{draw_away.odds:.2f}* (ID: {draw_away.id})")
                
                if dc_parts:
                    market_lines.append("\n*Double Chance:*\n" + "\n".join(dc_parts))

            # 3. Format Totals (Over/Under), combining 'totals', 'alternate_totals', 'goals_over_under'
            all_totals_outcomes = {
                **aggregated_outcomes.get('totals', {}), 
                **aggregated_outcomes.get('alternate_totals', {}),
                **aggregated_outcomes.get('goals_over_under', {})
            }
            if all_totals_outcomes:
                totals_by_point: Dict[float, Dict[str, MarketOutcome]] = {}
                for outcome in all_totals_outcomes.values():
                    if outcome.point_value is not None:
                        if outcome.point_value not in totals_by_point:
                            totals_by_point[outcome.point_value] = {}
                        if 'over' in outcome.outcome_name.lower():
                            totals_by_point[outcome.point_value]['over'] = outcome
                        elif 'under' in outcome.outcome_name.lower():
                            totals_by_point[outcome.point_value]['under'] = outcome

                sorted_points = sorted(totals_by_point.keys())
                totals_parts = []
                # Show up to MAX_TOTALS_LINES_TO_DISPLAY most common lines
                for point in sorted_points[:MAX_TOTALS_LINES_TO_DISPLAY]:
                    over_outcome = totals_by_point[point].get('over')
                    under_outcome = totals_by_point[point].get('under')
                    over_str = f"Over {point:.1f}: *{over_outcome.odds:.2f}* (ID: {over_outcome.id})" if over_outcome else ""
                    under_str = f"Under {point:.1f}: *{under_outcome.odds:.2f}* (ID: {under_outcome.id})" if under_outcome else ""
                    if over_str and under_str:
                        totals_parts.append(f"  - {over_str}")
                        totals_parts.append(f"  - {under_str}")
                    elif over_str or under_str:
                        totals_parts.append(f"  - {over_str or under_str}")

                if totals_parts:
                    market_lines.append("\n*Total Goals (Over/Under):*\n" + "\n".join(totals_parts))

            # 4. Format BTTS (Both Teams To Score)
            if 'btts' in aggregated_outcomes or 'both_teams_score' in aggregated_outcomes:
                btts_outcomes = aggregated_outcomes.get('btts') or aggregated_outcomes.get('both_teams_score') or {}
                yes_odds = btts_outcomes.get('Yes-') or btts_outcomes.get('Both Teams Score-')
                no_odds = btts_outcomes.get('No-') or btts_outcomes.get('Not Both Teams Score-')
                btts_parts = []
                if yes_odds: btts_parts.append(f"  - Yes: *{yes_odds.odds:.2f}* (ID: {yes_odds.id})")
                if no_odds: btts_parts.append(f"  - No: *{no_odds.odds:.2f}* (ID: {no_odds.id})")
                if btts_parts:
                    market_lines.append("\n*Both Teams To Score:*\n" + "\n".join(btts_parts))

            # 5. Format Draw No Bet
            if 'draw_no_bet' in aggregated_outcomes or 'drawnob' in aggregated_outcomes:
                dnb_outcomes = aggregated_outcomes.get('draw_no_bet') or aggregated_outcomes.get('drawnob') or {}
                home_dnb = dnb_outcomes.get(f"{fixture.home_team.name}-") or dnb_outcomes.get('Home-')
                away_dnb = dnb_outcomes.get(f"{fixture.away_team.name}-") or dnb_outcomes.get('Away-')
                
                dnb_parts = []
                if home_dnb: dnb_parts.append(f"  - {fixture.home_team.name}: *{home_dnb.odds:.2f}* (ID: {home_dnb.id})")
                if away_dnb: dnb_parts.append(f"  - {fixture.away_team.name}: *{away_dnb.odds:.2f}* (ID: {away_dnb.id})")
                
                if dnb_parts:
                    market_lines.append("\n*Draw No Bet:*\n" + "\n".join(dnb_parts))

            # 6. Format Asian Handicap (show ALL lines, not just the closest to 0)
            if 'handicap' in aggregated_outcomes or 'asian_handicap' in aggregated_outcomes or 'spreads' in aggregated_outcomes:
                handicap_outcomes = (aggregated_outcomes.get('handicap') or 
                                    aggregated_outcomes.get('asian_handicap') or 
                                    aggregated_outcomes.get('spreads') or {})
                
                formatted_handicap = _format_handicap_market(handicap_outcomes, fixture, "Asian Handicap")
                if formatted_handicap:
                    market_lines.append(formatted_handicap)

            # 7. Format Correct Score (show top MAX_CORRECT_SCORES_TO_DISPLAY most likely scores)
            if 'correct_score' in aggregated_outcomes or 'correctscore' in aggregated_outcomes:
                cs_outcomes = aggregated_outcomes.get('correct_score') or aggregated_outcomes.get('correctscore') or {}
                
                # Sort by odds (lower odds = more likely)
                sorted_scores = sorted(cs_outcomes.items(), key=lambda x: x[1].odds)[:MAX_CORRECT_SCORES_TO_DISPLAY]
                
                cs_parts = []
                for score_key, outcome in sorted_scores:
                    cs_parts.append(f"  - {outcome.outcome_name}: *{outcome.odds:.2f}* (ID: {outcome.id})")
                
                if cs_parts:
                    market_lines.append("\n*Correct Score (Top Picks):*\n" + "\n".join(cs_parts))

            # 8. Format Odd/Even Goals
            if 'odd_even' in aggregated_outcomes or 'oddeven' in aggregated_outcomes or 'goals_odd_even' in aggregated_outcomes:
                oe_outcomes = (aggregated_outcomes.get('odd_even') or 
                              aggregated_outcomes.get('oddeven') or 
                              aggregated_outcomes.get('goals_odd_even') or {})
                
                odd_outcome = oe_outcomes.get('Odd-')
                even_outcome = oe_outcomes.get('Even-')
                
                oe_parts = []
                if odd_outcome: oe_parts.append(f"  - Odd: *{odd_outcome.odds:.2f}* (ID: {odd_outcome.id})")
                if even_outcome: oe_parts.append(f"  - Even: *{even_outcome.odds:.2f}* (ID: {even_outcome.id})")
                
                if oe_parts:
                    market_lines.append("\n*Odd/Even Goals:*\n" + "\n".join(oe_parts))
            
            # 9. Format Asian Handicap (1st Half)
            if 'handicap_1h' in aggregated_outcomes:
                formatted_handicap = _format_handicap_market(
                    aggregated_outcomes.get('handicap_1h', {}), 
                    fixture, 
                    "Asian Handicap (1st Half)"
                )
                if formatted_handicap:
                    market_lines.append(formatted_handicap)
            
            # 10. Format Asian Handicap (2nd Half)
            if 'handicap_2h' in aggregated_outcomes:
                formatted_handicap = _format_handicap_market(
                    aggregated_outcomes.get('handicap_2h', {}), 
                    fixture, 
                    "Asian Handicap (2nd Half)"
                )
                if formatted_handicap:
                    market_lines.append(formatted_handicap)
            
            # 11. Format Totals (1st Half)
            if 'totals_1h' in aggregated_outcomes:
                formatted_totals = _format_totals_market(
                    aggregated_outcomes.get('totals_1h', {}),
                    "Total Goals (1st Half)",
                    MAX_TOTALS_LINES_TO_DISPLAY
                )
                if formatted_totals:
                    market_lines.append(formatted_totals)
            
            # 12. Format Totals (2nd Half)
            if 'totals_2h' in aggregated_outcomes:
                formatted_totals = _format_totals_market(
                    aggregated_outcomes.get('totals_2h', {}),
                    "Total Goals (2nd Half)",
                    MAX_TOTALS_LINES_TO_DISPLAY
                )
                if formatted_totals:
                    market_lines.append(formatted_totals)
            
            # 13. Format any OTHER bet types not covered above (e.g., Halftime/Fulltime, etc.)
            # These are bet types saved with generic keys like "bet_10", "bet_11", etc.
            known_market_keys = {
                'h2h', '1x2', 'match_winner',
                'double_chance', 'doublechance',
                'totals', 'alternate_totals', 'goals_over_under', 'totals_1h', 'totals_2h',
                'btts', 'both_teams_score',
                'draw_no_bet', 'drawnob',
                'handicap', 'asian_handicap', 'spreads', 'handicap_1h', 'handicap_2h',
                'correct_score', 'correctscore',
                'odd_even', 'oddeven', 'goals_odd_even'
            }
            
            for market_key, outcomes_dict in aggregated_outcomes.items():
                if market_key not in known_market_keys and outcomes_dict:
                    # Format the market name from the key
                    market_name = market_key.replace('_', ' ').title()
                    if market_key.startswith('bet_'):
                        # Get a better name from the actual market category if available
                        # Use the first outcome's market to get category name
                        try:
                            first_outcome = next(iter(outcomes_dict.values()))
                            if hasattr(first_outcome, 'market') and hasattr(first_outcome.market, 'category'):
                                market_name = first_outcome.market.category.name
                        except (StopIteration, AttributeError):
                            # If we can't get a better name, keep the formatted key name
                            pass
                    
                    other_parts = []
                    for outcome in outcomes_dict.values():
                        other_parts.append(f"  - {outcome.outcome_name}: *{outcome.odds:.2f}* (ID: {outcome.id})")
                    
                    if other_parts:
                        # Display all outcomes for unrecognized markets
                        # (No truncation - WhatsApp can handle messages up to 4096 characters)
                        market_lines.append(f"\n*{market_name}:*\n" + "\n".join(other_parts))
            
            # ONLY include fixtures that have at least one market with odds
            if market_lines:
                # Store base fixture info separately for potential reuse
                base_fixture_info = line.strip()
                fixture_text = line + "\n" + "\n".join(market_lines)
                fixture_text = fixture_text.strip()
                
                # Check if single fixture exceeds safe limit (leaving room for header/footer)
                # WhatsApp limit is 4096, we use 4000 for parts, but a single fixture should be max 3500
                # to allow room for header and separator
                if len(fixture_text) > MAX_SINGLE_FIXTURE_LENGTH:
                    logger.warning(f"Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) "
                                 f"exceeds safe length ({len(fixture_text)} > {MAX_SINGLE_FIXTURE_LENGTH} chars). "
                                 f"Truncating market display...")
                    # Truncate by reducing the number of market lines shown
                    # Keep essential markets: Match Winner, Totals, BTTS (first 3 market sections)
                    essential_markets = market_lines[:3]
                    truncated_line = base_fixture_info + "\n" + "\n".join(essential_markets)
                    truncated_line += "\n\n_(...additional markets not shown due to length)_"
                    fixture_text = truncated_line.strip()
                    logger.info(f"Truncated fixture {fixture.id} to {len(fixture_text)} chars (kept {len(essential_markets)}/{len(market_lines)} market sections)")
                
                individual_item_strings.append(fixture_text)
                logger.debug(f"Added fixture {fixture.id} with {len(market_lines)} market sections to output (length: {len(fixture_text)} chars)")
            else:
                logger.info(f"SKIPPING fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) - no odds available")

    elif data_type == "finished_results":
        data_type_label = "Recent Results"
        main_header = "⚽ *Recent Results*"
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
            logger.info(f"No {data_type_label.lower()} found{league_info} for the specified criteria. Returning None.")
            return None
        
        num_fixtures_to_display = 10
        logger.debug(f"Formatting details for up to {min(fixtures_qs.count(), num_fixtures_to_display)} finished matches.")
        
        for fixture in fixtures_qs[:num_fixtures_to_display]:
            match_time_local = timezone.localtime(fixture.match_date)
            time_str = match_time_local.strftime('%a, %b %d - %I:%M %p')
            
            line = f"\n🏆 *{fixture.league.name}* (ID: {fixture.id})"
            line += f"\n🗓️ {time_str}"
            line += f"\n{fixture.home_team.name} vs {fixture.away_team.name}"
            
            if fixture.home_team_score is not None:
                line += f" | Result: *{fixture.home_team_score} - {fixture.away_team_score}*"
            
            individual_item_strings.append(line.strip())

    else:
        logger.warning(f"Invalid data type requested: '{data_type}'. Returning None.")
        return None

    if not individual_item_strings:
        reason = " All fixtures were skipped (no odds available)." if data_type == "scheduled_fixtures" else ""
        logger.warning(f"No {data_type_label} to display.{reason} Returning None.")
        return None

    logger.info(f"Successfully formatted {len(individual_item_strings)} items for {data_type_label}.")

    # Assemble message parts
    all_message_parts: List[str] = []
    current_part_items: List[str] = []
    current_part_length = 0
    header_allowance = len(main_header) + len("\n\n")

    for i, item_str in enumerate(individual_item_strings):
        separator_len = len(MESSAGE_PART_SEPARATOR) if current_part_items else 0
        prospective_item_len = separator_len + len(item_str)
        current_total_prospective_len = current_part_length + prospective_item_len

        if not all_message_parts:
            current_total_prospective_len += header_allowance

        if current_total_prospective_len > MAX_CHARS_PER_MESSAGE_PART and current_part_items:
            part_to_add = MESSAGE_PART_SEPARATOR.join(current_part_items)
            if not all_message_parts:
                part_to_add = main_header + "\n\n" + part_to_add
            all_message_parts.append(part_to_add)
            
            current_part_items = [item_str]
            current_part_length = len(item_str)
        else:
            current_part_items.append(item_str)
            current_part_length += prospective_item_len

    if current_part_items:
        final_part_str = MESSAGE_PART_SEPARATOR.join(current_part_items)
        if not all_message_parts:
            final_part_str = main_header + "\n\n" + final_part_str
        
        # Final safety check: ensure this part doesn't exceed WhatsApp's limit (4096)
        if len(final_part_str) > 4096:
            logger.error(f"CRITICAL: Final message part exceeds WhatsApp limit! Length: {len(final_part_str)}. "
                        f"This should not happen after fixture truncation. Splitting further...")
            # Emergency split - this shouldn't happen if our MAX_SINGLE_FIXTURE_LENGTH is correct
            # but provides a failsafe
            while len(final_part_str) > MAX_CHARS_PER_MESSAGE_PART and current_part_items:
                # Remove last item and save it for next part
                removed_item = current_part_items.pop()
                temp_part = MESSAGE_PART_SEPARATOR.join(current_part_items)
                if not all_message_parts:
                    temp_part = main_header + "\n\n" + temp_part
                if len(temp_part) <= MAX_CHARS_PER_MESSAGE_PART:
                    all_message_parts.append(temp_part)
                    current_part_items = [removed_item]
                    final_part_str = removed_item
                    break
        
        all_message_parts.append(final_part_str)

    if all_message_parts:
        if len(all_message_parts[-1]) + len(footer_string) <= MAX_CHARS_PER_MESSAGE_PART:
            all_message_parts[-1] += footer_string
        else:
            all_message_parts.append(footer_string)
    
    logger.info(f"Formatted data for data_type='{data_type}' into {len(all_message_parts)} parts.")
    return all_message_parts


def parse_betting_string(betting_string: str) -> dict:
    """
    Parses a free-form betting string into a list of market outcome IDs and a stake.
    This version is optimized to reduce database queries for multi-line bet slips.
    """
    # --- Local Import to Prevent Circular Dependency ---
    from football_data_app.models import FootballFixture, MarketOutcome

    lines = [line.strip() for line in betting_string.split('\n') if line.strip()]
    parsed_bets = []
    stake_amount = Decimal('0.0')
    fixture_ids_to_fetch = set()

    stake_pattern = re.compile(r"Stake\s*\$?\s*([\d\.,]+)", re.IGNORECASE)
    bet_line_pattern = re.compile(r"(\d+)\s+(.*)", re.IGNORECASE)

    # --- First Pass: Parse lines and collect fixture IDs ---
    for line in lines:
        stake_match = stake_pattern.match(line)
        if stake_match:
            try:
                stake_str = stake_match.group(1).replace(',', '')
                stake_amount = Decimal(stake_str)
            except (ValueError, TypeError):
                return {"success": False, "message": f"Invalid stake amount: {stake_match.group(1)}"}
            continue

        bet_line_match = bet_line_pattern.match(line)
        if bet_line_match:
            try:
                fixture_id = int(bet_line_match.group(1).strip())
                option_text = bet_line_match.group(2).strip()
                fixture_ids_to_fetch.add(fixture_id)
                parsed_bets.append({'fixture_id': fixture_id, 'option_text': option_text, 'original_line': line})
            except (ValueError, TypeError):
                return {"success": False, "message": f"Invalid fixture ID in line: '{line}'"}
        else:
            return {"success": False, "message": f"Unrecognized betting line format: '{line}'"}

    if not parsed_bets:
        return {"success": False, "message": "No valid betting options found in the message."}
    if stake_amount <= 0:
        return {"success": False, "message": "Stake amount not found or is invalid. Please specify 'Stake $AMOUNT'."}

    # --- Bulk Fetch Data ---
    fixtures_map = {f.id: f for f in FootballFixture.objects.filter(id__in=fixture_ids_to_fetch).select_related('home_team', 'away_team')}
    
    outcomes_qs = MarketOutcome.objects.filter(
        market__fixture_id__in=fixture_ids_to_fetch,
        is_active=True
    ).select_related('market')

    outcomes_by_fixture = {}
    for outcome in outcomes_qs:
        fid = outcome.market.fixture_id
        if fid not in outcomes_by_fixture:
            outcomes_by_fixture[fid] = []
        outcomes_by_fixture[fid].append(outcome)

    # --- Second Pass: Match outcomes using in-memory data ---
    market_outcome_ids = []
    for bet in parsed_bets:
        fixture_id = bet['fixture_id']
        option_text = bet['option_text']
        
        matched_fixture = fixtures_map.get(fixture_id)
        if not matched_fixture:
            return {"success": False, "message": f"Could not find a fixture for ID '{fixture_id}'."}

        outcomes_for_fixture = outcomes_by_fixture.get(fixture_id, [])
        if not outcomes_for_fixture:
            return {"success": False, "message": f"No active betting markets found for fixture ID '{fixture_id}'."}

        found_outcome = None
        
        # --- Enhanced Outcome Matching Logic (applied to in-memory list) ---
        # 1. Try exact outcome_name match first
        for outcome in outcomes_for_fixture:
            if outcome.outcome_name.lower() == option_text.lower():
                found_outcome = outcome
                break
        
        # 2. Totals (Over/Under) matching
        if not found_outcome:
            totals_match = re.match(r"(over|under|o|u)\s*(\d+\.?\d*)", option_text, re.IGNORECASE)
            if totals_match:
                bet_type, point_val_str = totals_match.groups()
                point_val = Decimal(point_val_str)
                outcome_name_to_find = 'over' if bet_type.lower().startswith('o') else 'under'
                for outcome in outcomes_for_fixture:
                    if outcome.market.api_market_key in ['totals', 'alternate_totals'] and \
                       outcome.point_value is not None and Decimal(str(outcome.point_value)) == point_val and \
                       outcome_name_to_find in outcome.outcome_name.lower():
                        found_outcome = outcome
                        break
        
        # 3. BTTS (Both Teams To Score) matching
        if not found_outcome:
            btts_text = option_text.lower().replace(" ", "")
            outcome_name_to_find = None
            if btts_text in ['bttsyes', 'gg']: outcome_name_to_find = 'Yes'
            elif btts_text in ['bttsno', 'ng']: outcome_name_to_find = 'No'
            if outcome_name_to_find:
                for outcome in outcomes_for_fixture:
                    if outcome.market.api_market_key == 'btts' and outcome.outcome_name == outcome_name_to_find:
                        found_outcome = outcome
                        break
        
        # 4. H2H (Home/Away/Draw) matching
        if not found_outcome:
            h2h_text = option_text.lower()
            outcome_name_to_find = None
            if h2h_text in ['home', '1', matched_fixture.home_team.name.lower()]:
                outcome_name_to_find = matched_fixture.home_team.name
            elif h2h_text in ['away', '2', matched_fixture.away_team.name.lower()]:
                outcome_name_to_find = matched_fixture.away_team.name
            elif h2h_text in ['draw', 'x']:
                outcome_name_to_find = 'Draw'
            if outcome_name_to_find:
                for outcome in outcomes_for_fixture:
                    if outcome.market.api_market_key == 'h2h' and outcome.outcome_name == outcome_name_to_find:
                        found_outcome = outcome
                        break

        if found_outcome:
            market_outcome_ids.append(str(found_outcome.id))
        else:
            return {"success": False, "message": f"Could not find a valid betting option for '{option_text}' in fixture '{matched_fixture.home_team.name} vs {matched_fixture.away_team.name}' (ID: {matched_fixture.id})."}

    return {
        "success": True,
        "market_outcome_ids": market_outcome_ids,
        "stake": float(stake_amount),
        "message": "Betting string parsed successfully."
    }


def settle_ticket(ticket_id: int):
    """
    Checks the status of all bets on a ticket and updates the ticket's status.
    If the ticket is won, it processes the payout. Handles PUSHed bets correctly.
    Triggers a notification to the user if the status changes.
    """
    # --- Local Imports to Prevent Circular Dependency ---
    from football_data_app.models import BetTicket
    from .tasks import send_bet_ticket_settlement_notification_task

    log_prefix = f"[Settle Ticket - ID: {ticket_id}]"
    logger.info(f"{log_prefix} Starting settlement process.")

    try:
        with transaction.atomic():
            try:
                # Lock the ticket to prevent race conditions
                ticket = BetTicket.objects.select_for_update().get(pk=ticket_id)
            except BetTicket.DoesNotExist:
                logger.error(f"{log_prefix} Failed: BetTicket not found in database.")
                return

            # Only process tickets that are currently PENDING or PLACED
            if ticket.status not in ['PENDING', 'PLACED']:
                logger.info(f"{log_prefix} Skipping: Ticket is already settled with status '{ticket.status}'.")
                return

            bets = ticket.bets.select_related('market_outcome').all()
            if not bets.exists():
                logger.warning(f"{log_prefix} Ticket has no bets. Marking as LOST.")
                ticket.status = 'LOST'
                ticket.save(update_fields=['status'])
                send_bet_ticket_settlement_notification_task.delay(ticket_id=ticket.id, new_status='LOST', winnings="0.00")
                return

            bet_statuses = {bet.status for bet in bets}
            logger.debug(f"{log_prefix} Found bet statuses: {bet_statuses}")

            # If any bet is still pending, the ticket is not ready for settlement.
            if 'PENDING' in bet_statuses:
                logger.info(f"{log_prefix} Ticket still has pending bets. No status change.")
                return

            # Determine the final ticket status
            new_status = ''
            winnings = Decimal('0.00')

            # Check if any bet lost
            if 'LOST' in bet_statuses:
                new_status = 'LOST'
                logger.info(f"{log_prefix} At least one bet was LOST. Setting ticket status to LOST.")
            # Check if we have any winning bets (may also have REFUNDED/PUSH bets)
            elif 'WON' in bet_statuses:
                new_status = 'WON'
                # Calculate winnings, treating PUSH/REFUNDED odds as 1
                total_odds = Decimal('1.0')
                for bet in bets:
                    if bet.status == 'WON':
                        total_odds *= bet.market_outcome.odds
                    # For REFUNDED/PUSH bets, multiply by 1.0 (no effect)
                
                # Calculate actual winnings
                winnings = ticket.total_stake * total_odds
                
                logger.info(f"{log_prefix} Ticket WON. Stake: {ticket.total_stake}, Total Odds: {total_odds:.2f}, Winnings: {winnings:.2f}.")
                
                # Payout to user's wallet
                if ticket.user and hasattr(ticket.user, 'wallet'):
                    wallet = ticket.user.wallet
                    wallet.add_funds(
                        amount=winnings,
                        description=f"Winnings from bet ticket ID: {ticket.id}",
                        transaction_type='BET_WON'
                    )
                    logger.info(f"{log_prefix} Paid out ${winnings:.2f} to user '{ticket.user.username}' (Wallet ID: {wallet.id}).")
                else:
                    logger.error(f"{log_prefix} Cannot payout - user or wallet not found.")
                    raise ValueError("User or wallet not found for payout")
            # All bets are PUSH/REFUNDED
            else:
                new_status = 'REFUNDED'
                winnings = ticket.total_stake # Refund stake
                
                logger.info(f"{log_prefix} All bets are REFUNDED/PUSH. Refunding stake of ${winnings:.2f}.")
                
                # Refund to user's wallet
                if ticket.user and hasattr(ticket.user, 'wallet'):
                    wallet = ticket.user.wallet
                    wallet.add_funds(
                        amount=winnings,
                        description=f"Stake refund for pushed bet ticket ID: {ticket.id}",
                        transaction_type='BET_REFUNDED'
                    )
                    logger.info(f"{log_prefix} Refunded stake of ${winnings:.2f} to user '{ticket.user.username}' (Wallet ID: {wallet.id}).")
                else:
                    logger.error(f"{log_prefix} Cannot refund - user or wallet not found.")
                    raise ValueError("User or wallet not found for refund")

            ticket.status = new_status
            ticket.save(update_fields=['status'])
            logger.info(f"{log_prefix} Final status updated to {new_status} in database.")

        # Trigger notification task outside the transaction to avoid issues
        logger.info(f"{log_prefix} Triggering settlement notification task for user.")
        send_bet_ticket_settlement_notification_task.delay(
            ticket_id=ticket.id,
            new_status=new_status,
            winnings=f"{winnings:.2f}"
        )
    except Exception as e:
        logger.error(f"{log_prefix} Error during ticket settlement: {str(e)}", exc_info=True)
        # Re-raise to ensure transaction is rolled back
        raise


def generate_fixtures_pdf(
    data_type: str,
    league_code: Optional[str] = None,
    days_ahead: int = 10,
    days_past: int = 4
) -> Optional[str]:
    """
    Generates a PDF document containing football fixtures with odds.
    
    Args:
        data_type: Type of data ('scheduled_fixtures' or 'finished_results')
        league_code: Optional league filter
        days_ahead: Days ahead for scheduled fixtures
        days_past: Days past for finished results
    
    Returns:
        Absolute path to generated PDF file, or None if no data
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from django.conf import settings
    import os
    
    # Local imports
    from football_data_app.models import FootballFixture, MarketOutcome, Market
    
    logger.info(f"Generating PDF for data_type='{data_type}', league_code='{league_code}'")
    
    # Query fixtures
    now = timezone.now()
    
    if data_type == "scheduled_fixtures":
        start_date = now
        end_date = now + timedelta(days=days_ahead)
        fixtures_qs = FootballFixture.objects.filter(
            Q(status=FootballFixture.FixtureStatus.SCHEDULED, match_date__gte=start_date, match_date__lte=end_date) |
            Q(status=FootballFixture.FixtureStatus.LIVE)
        ).select_related('home_team', 'away_team', 'league').prefetch_related(
            Prefetch('markets', queryset=Market.objects.filter(is_active=True)),
            Prefetch('markets__outcomes', queryset=MarketOutcome.objects.filter(is_active=True))
        ).order_by('match_date')
        title = "Upcoming Football Fixtures"
    elif data_type == "finished_results":
        end_date = now
        start_date = now - timedelta(days=days_past)
        fixtures_qs = FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.FINISHED,
            match_date__gte=start_date,
            match_date__lte=end_date
        ).select_related('home_team', 'away_team', 'league').order_by('-match_date')
        title = "Recent Football Results"
    else:
        logger.error(f"Invalid data_type: {data_type}")
        return None
    
    if league_code:
        fixtures_qs = fixtures_qs.filter(league__api_id=league_code)
    
    if not fixtures_qs.exists():
        logger.info("No fixtures found for PDF generation")
        return None
    
    # Create PDF
    media_root = settings.MEDIA_ROOT
    pdf_dir = os.path.join(media_root, 'fixtures_pdfs')
    os.makedirs(pdf_dir, exist_ok=True)
    
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    filename = f"fixtures_{timestamp}.pdf"
    filepath = os.path.join(pdf_dir, filename)
    
    doc = SimpleDocTemplate(filepath, pagesize=letter,
                          rightMargin=0.5*inch, leftMargin=0.5*inch,
                          topMargin=0.75*inch, bottomMargin=0.75*inch)
    
    # Container for PDF elements
    elements = []
    styles = getSampleStyleSheet()
    
    # Title style
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a472a'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    # Add title
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 0.3*inch))
    
    # Add timestamp
    now_harare = timezone.localtime(now)
    datetime_str = now_harare.strftime('%B %d, %Y at %I:%M %p %Z')
    timestamp_style = ParagraphStyle('Timestamp', parent=styles['Normal'], 
                                     fontSize=10, textColor=colors.grey, 
                                     alignment=TA_CENTER)
    elements.append(Paragraph(f"Generated on {datetime_str}", timestamp_style))
    elements.append(Spacer(1, 0.4*inch))
    
    # Process fixtures
    fixtures_added = 0
    for fixture in fixtures_qs[:40]:  # Limit to 40 fixtures
        if fixtures_added > 0 and fixtures_added % 5 == 0:
            elements.append(PageBreak())
        
        # Fixture header
        match_time_local = timezone.localtime(fixture.match_date)
        time_str = match_time_local.strftime('%a, %b %d - %I:%M %p')
        
        fixture_header_style = ParagraphStyle('FixtureHeader', parent=styles['Heading2'],
                                             fontSize=12, textColor=colors.HexColor('#2c5f2d'),
                                             spaceAfter=6, fontName='Helvetica-Bold')
        
        league_text = f"<b>{fixture.league.name}</b>"
        elements.append(Paragraph(league_text, fixture_header_style))
        
        match_text = f"<b>{fixture.home_team.name}</b> vs <b>{fixture.away_team.name}</b>"
        if fixture.status == FootballFixture.FixtureStatus.LIVE and fixture.home_team_score is not None:
            match_text = f"<b>{fixture.home_team.name} {fixture.home_team_score} - {fixture.away_team_score} {fixture.away_team.name}</b> (LIVE)"
        elif fixture.status == FootballFixture.FixtureStatus.FINISHED and fixture.home_team_score is not None:
            match_text = f"<b>{fixture.home_team.name} {fixture.home_team_score} - {fixture.away_team_score} {fixture.away_team.name}</b>"
        
        match_style = ParagraphStyle('Match', parent=styles['Normal'], fontSize=11, 
                                     spaceAfter=4)
        elements.append(Paragraph(match_text, match_style))
        elements.append(Paragraph(f"<i>{time_str}</i> | Fixture ID: {fixture.id}", 
                                 ParagraphStyle('Time', parent=styles['Normal'], 
                                              fontSize=9, textColor=colors.grey)))
        elements.append(Spacer(1, 0.15*inch))
        
        # Get odds data for scheduled fixtures
        if data_type == "scheduled_fixtures":
            # Aggregate outcomes
            aggregated_outcomes: Dict[str, Dict[str, MarketOutcome]] = {}
            for market in fixture.markets.all():
                market_key = market.api_market_key
                if market_key not in aggregated_outcomes:
                    aggregated_outcomes[market_key] = {}
                for outcome in market.outcomes.all():
                    outcome_identifier = f"{outcome.outcome_name}-{outcome.point_value if outcome.point_value is not None else ''}"
                    current_best = aggregated_outcomes[market_key].get(outcome_identifier)
                    if current_best is None or outcome.odds > current_best.odds:
                        aggregated_outcomes[market_key][outcome_identifier] = outcome
            
            if aggregated_outcomes:
                # Create odds table
                odds_data = [['Market', 'Selection', 'Odds', 'ID']]
                
                # Add Match Winner
                if 'h2h' in aggregated_outcomes or '1x2' in aggregated_outcomes:
                    h2h_outcomes = aggregated_outcomes.get('h2h') or aggregated_outcomes.get('1x2') or {}
                    home_odds = h2h_outcomes.get(f"{fixture.home_team.name}-") or h2h_outcomes.get('Home-')
                    draw_odds = h2h_outcomes.get('Draw-')
                    away_odds = h2h_outcomes.get(f"{fixture.away_team.name}-") or h2h_outcomes.get('Away-')
                    
                    if home_odds: odds_data.append(['Match Winner', fixture.home_team.name, f"{home_odds.odds:.2f}", str(home_odds.id)])
                    if draw_odds: odds_data.append(['', 'Draw', f"{draw_odds.odds:.2f}", str(draw_odds.id)])
                    if away_odds: odds_data.append(['', fixture.away_team.name, f"{away_odds.odds:.2f}", str(away_odds.id)])
                
                # Add BTTS
                if 'btts' in aggregated_outcomes:
                    btts_outcomes = aggregated_outcomes.get('btts', {})
                    yes_odds = btts_outcomes.get('Yes-')
                    no_odds = btts_outcomes.get('No-')
                    if yes_odds: odds_data.append(['Both Teams Score', 'Yes', f"{yes_odds.odds:.2f}", str(yes_odds.id)])
                    if no_odds: odds_data.append(['', 'No', f"{no_odds.odds:.2f}", str(no_odds.id)])
                
                # Add Totals (limited)
                all_totals = {**aggregated_outcomes.get('totals', {}), **aggregated_outcomes.get('goals_over_under', {})}
                if all_totals:
                    totals_by_point: Dict[float, Dict[str, MarketOutcome]] = {}
                    for outcome in all_totals.values():
                        if outcome.point_value is not None:
                            if outcome.point_value not in totals_by_point:
                                totals_by_point[outcome.point_value] = {}
                            if 'over' in outcome.outcome_name.lower():
                                totals_by_point[outcome.point_value]['over'] = outcome
                            elif 'under' in outcome.outcome_name.lower():
                                totals_by_point[outcome.point_value]['under'] = outcome
                    
                    for point in sorted(totals_by_point.keys())[:2]:  # Show top 2 lines
                        over_outcome = totals_by_point[point].get('over')
                        under_outcome = totals_by_point[point].get('under')
                        if over_outcome:
                            odds_data.append(['Total Goals', f'Over {point:.1f}', f"{over_outcome.odds:.2f}", str(over_outcome.id)])
                        if under_outcome:
                            odds_data.append(['', f'Under {point:.1f}', f"{under_outcome.odds:.2f}", str(under_outcome.id)])
                
                if len(odds_data) > 1:  # Has data beyond header
                    table = Table(odds_data, colWidths=[1.8*inch, 1.8*inch, 0.7*inch, 0.7*inch])
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5f2d')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 10),
                        ('FONTSIZE', (0, 1), (-1, -1), 9),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                        ('TOPPADDING', (0, 1), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')])
                    ]))
                    elements.append(table)
                else:
                    elements.append(Paragraph("<i>No odds available</i>", 
                                            ParagraphStyle('NoOdds', parent=styles['Normal'], 
                                                         fontSize=9, textColor=colors.grey)))
            else:
                elements.append(Paragraph("<i>No odds available</i>", 
                                        ParagraphStyle('NoOdds', parent=styles['Normal'], 
                                                     fontSize=9, textColor=colors.grey)))
        
        elements.append(Spacer(1, 0.3*inch))
        fixtures_added += 1
    
    # Add footer
    elements.append(Spacer(1, 0.2*inch))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, 
                                 textColor=colors.grey, alignment=TA_CENTER)
    elements.append(Paragraph("Generated by BetBlitz - Your Football Betting Platform", footer_style))
    
    # Build PDF
    try:
        doc.build(elements)
        logger.info(f"PDF generated successfully: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Error generating PDF: {e}", exc_info=True)
        return None