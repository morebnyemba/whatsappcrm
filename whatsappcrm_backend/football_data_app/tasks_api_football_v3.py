"""
Celery tasks for fetching and processing football data using API-Football v3 (api-football.com)
This module provides robust tasks for the new recommended API-Football v3 provider.
"""

import logging
from django.conf import settings
from celery import chord, shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from datetime import timedelta, datetime, timezone as dt_timezone
from decimal import Decimal
from typing import List, Dict, Any, Optional
import random
import time

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .utils import settle_ticket, upsert_market_outcome
from .api_football_v3_client import APIFootballV3Client, APIFootballV3Exception

from meta_integration.utils import send_whatsapp_message, create_text_message_data

logger = logging.getLogger(__name__)

# --- Configuration ---
API_FOOTBALL_V3_LEAD_TIME_DAYS = getattr(settings, 'API_FOOTBALL_V3_LEAD_TIME_DAYS', 7)
API_FOOTBALL_V3_EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'API_FOOTBALL_V3_EVENT_DISCOVERY_STALENESS_HOURS', 6)
API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES = getattr(settings, 'API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES', 60)
API_FOOTBALL_V3_ASSUMED_COMPLETION_MINUTES = getattr(settings, 'API_FOOTBALL_V3_ASSUMED_COMPLETION_MINUTES', 120)
API_FOOTBALL_V3_MAX_EVENT_RETRIES = getattr(settings, 'API_FOOTBALL_V3_MAX_EVENT_RETRIES', 3)
API_FOOTBALL_V3_EVENT_RETRY_DELAY = getattr(settings, 'API_FOOTBALL_V3_EVENT_RETRY_DELAY', 300)
# Safety cap on /odds pagination per (league, day) bulk fetch. Each page is one
# billable request; a single league-day rarely exceeds a couple of pages.
API_FOOTBALL_V3_MAX_ODDS_PAGES = getattr(settings, 'API_FOOTBALL_V3_MAX_ODDS_PAGES', 25)

# Setup command reference for consistent messaging
LEAGUE_SETUP_COMMAND = "python manage.py football_league_setup_v3"
LEAGUE_SETUP_COMMAND_DOCKER = "docker-compose exec backend python manage.py football_league_setup_v3"

# --- Helper Functions ---

def get_current_season() -> int:
    """
    Get the current season from Configuration model or fallback to settings/default.
    
    Priority:
    1. Database Configuration (provider_name='API-Football', is_active=True)
    2. Settings API_FOOTBALL_V3_CURRENT_SEASON
    3. Default: 2024
    
    Returns:
        Current season year as integer
    """
    try:
        from .models import Configuration
        config = Configuration.objects.filter(
            provider_name="API-Football",
            is_active=True
        ).first()
        if config and config.current_season:
            logger.debug(f"Current season loaded from database Configuration: {config.current_season}")
            return config.current_season
    except Exception as e:
        logger.warning(f"Could not load season from database Configuration: {e}")
    
    # Fallback to settings
    season = getattr(settings, 'API_FOOTBALL_V3_CURRENT_SEASON', 2024)
    logger.debug(f"Current season loaded from settings: {season}")
    return season


def parse_api_football_v3_datetime(timestamp_str: str) -> Optional[datetime]:
    """
    Parse datetime from API-Football v3 format.
    
    Per API-Football v3 documentation: https://www.api-football.com/documentation-v3
    - Timestamps are in ISO 8601 format (e.g., '2024-01-15T20:00:00+00:00')
    
    Args:
        timestamp_str: ISO 8601 timestamp string from the API
        
    Returns:
        Timezone-aware datetime object or None if parsing fails
    """
    if not timestamp_str:
        return None
    
    try:
        # Parse ISO 8601 format
        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Could not parse datetime: {timestamp_str}, error: {e}")
        return None


@transaction.atomic
def _map_bet_to_category_and_key(bet_name: str, bet_id):
    """Map an API-Football v3 bet ('Match Winner', 'Asian Handicap', ...) to
    our MarketCategory + api_market_key. Shared by the pre-match odds
    processor and the live-odds processor so the mapping never drifts
    between the two pipelines.

    Based on API-Football v3 documentation: https://www.api-football.com/documentation-v3
    """
    if bet_name == 'Match Winner' or bet_id == 1:
        category, _ = MarketCategory.objects.get_or_create(name='Match Winner')
        return category, 'h2h'
    if bet_name == 'Double Chance' or bet_id == 2:
        category, _ = MarketCategory.objects.get_or_create(name='Double Chance')
        return category, 'double_chance'
    if ('Asian Handicap' in bet_name or 'Handicap' in bet_name) or bet_id == 3:
        if '2nd Half' in bet_name or '2H' in bet_name or bet_id == 20:
            category, _ = MarketCategory.objects.get_or_create(name='Asian Handicap (2nd Half)')
            return category, 'handicap_2h'
        if '1st Half' in bet_name or '1H' in bet_name or bet_id == 19:
            category, _ = MarketCategory.objects.get_or_create(name='Asian Handicap (1st Half)')
            return category, 'handicap_1h'
        category, _ = MarketCategory.objects.get_or_create(name='Asian Handicap')
        return category, 'handicap'
    if 'Draw No Bet' in bet_name or bet_id == 4:
        category, _ = MarketCategory.objects.get_or_create(name='Draw No Bet')
        return category, 'draw_no_bet'
    if ('Goals' in bet_name and 'Over' in bet_name) or bet_id == 5:
        if '2nd Half' in bet_name or '2H' in bet_name or bet_id == 22:
            category, _ = MarketCategory.objects.get_or_create(name='Totals (2nd Half)')
            return category, 'totals_2h'
        if '1st Half' in bet_name or '1H' in bet_name or bet_id == 21:
            category, _ = MarketCategory.objects.get_or_create(name='Totals (1st Half)')
            return category, 'totals_1h'
        category, _ = MarketCategory.objects.get_or_create(name='Totals')
        return category, 'totals'
    if 'Odd/Even' in bet_name or bet_id == 7:
        category, _ = MarketCategory.objects.get_or_create(name='Odd/Even Goals')
        return category, 'odd_even'
    if 'Both Teams Score' in bet_name or bet_id == 8:
        category, _ = MarketCategory.objects.get_or_create(name='Both Teams To Score')
        return category, 'btts'
    if ('Exact Score' in bet_name or 'Correct Score' in bet_name) or bet_id == 9:
        category, _ = MarketCategory.objects.get_or_create(name='Correct Score')
        return category, 'correct_score'
    category, _ = MarketCategory.objects.get_or_create(name=bet_name)
    return category, (f"bet_{bet_id}" if bet_id else bet_name.lower().replace(' ', '_'))


def _parse_outcome_name_and_point(api_market_key: str, outcome_value: str, fixture: FootballFixture):
    """Derive (outcome_name, point_value) from a raw outcome value string
    ('Home', 'Over 2.5', 'Home -1.5', ...), mapping Home/Away to real team
    names where relevant. Shared by the pre-match and live-odds processors."""
    outcome_name = outcome_value
    point_value = None

    if api_market_key in ('h2h', 'draw_no_bet'):
        if outcome_value == 'Home':
            outcome_name = fixture.home_team.name
        elif outcome_value == 'Away':
            outcome_name = fixture.away_team.name

    if api_market_key in ('totals', 'handicap', 'handicap_1h', 'handicap_2h', 'totals_1h', 'totals_2h'):
        parts = outcome_value.split()
        if len(parts) >= 2:
            try:
                point_value = float(parts[-1])
                if 'handicap' in api_market_key:
                    if parts[0] == 'Home':
                        outcome_name = fixture.home_team.name
                    elif parts[0] == 'Away':
                        outcome_name = fixture.away_team.name
                else:
                    outcome_name = parts[0]
            except (ValueError, IndexError) as e:
                logger.debug(f"Could not parse point value from '{outcome_value}' for market key '{api_market_key}': {e}")

    return outcome_name, point_value


def _process_api_football_v3_odds_data(fixture: FootballFixture, odds_data: List[dict]):
    """
    Processes and saves odds/market data from API-Football v3 for a fixture.
    
    API-Football v3 odds structure:
    {
        'fixture': {'id': 12345},
        'league': {'id': 39, 'name': 'Premier League'},
        'bookmakers': [
            {
                'id': 8,
                'name': 'bet365',
                'bets': [
                    {
                        'id': 1,
                        'name': 'Match Winner',
                        'values': [
                            {'value': 'Home', 'odd': '2.50'},
                            {'value': 'Draw', 'odd': '3.10'},
                            {'value': 'Away', 'odd': '2.90'}
                        ]
                    }
                ]
            }
        ]
    }
    """
    logger.info(f"Processing odds data for fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name})")
    
    if not odds_data:
        logger.warning(f"No odds data provided for fixture {fixture.id}")
        return
    
    logger.info(f"Found {len(odds_data)} odds items to process")
    total_markets_created = 0
    total_outcomes_created = 0
    bookmakers_encountered = 0
    bookmakers_created = 0
    # Tracks which of this fixture's existing markets are still offered by each
    # bookmaker in this refresh, so a market a bookmaker has dropped entirely
    # (not just one outcome within a market that's still offered) gets
    # deactivated below rather than left active with odds that can never
    # change again.
    seen_market_ids_by_bookmaker_id = {}

    for odds_item in odds_data:
        bookmakers_list = odds_item.get('bookmakers', [])
        logger.info(f"Processing {len(bookmakers_list)} bookmakers for fixture {fixture.id}")
        
        for bookmaker_data in bookmakers_list:
            bookmaker_name = bookmaker_data.get('name', 'Unknown')
            bookmaker_id = bookmaker_data.get('id')
            
            # Create or get bookmaker
            bookmaker, bookmaker_created = Bookmaker.objects.get_or_create(
                api_bookmaker_key=str(bookmaker_id) if bookmaker_id else bookmaker_name.lower().replace(' ', '_'),
                defaults={'name': bookmaker_name}
            )
            bookmakers_encountered += 1
            if bookmaker_created:
                logger.info(f"Created new bookmaker: {bookmaker_name}")
                bookmakers_created += 1
            seen_market_ids = seen_market_ids_by_bookmaker_id.setdefault(bookmaker.id, set())

            # Process bets (markets)
            bets_list = bookmaker_data.get('bets', [])
            logger.debug(f"Processing {len(bets_list)} markets for bookmaker {bookmaker_name}")
            
            for bet_data in bets_list:
                bet_name = bet_data.get('name', 'Unknown Market')
                bet_id = bet_data.get('id')
                category, api_market_key = _map_bet_to_category_and_key(bet_name, bet_id)

                # Update the existing market in place if one already exists for this
                # fixture/bookmaker/market_key, instead of deleting and recreating it.
                # Market -> MarketOutcome -> Bet are all on_delete=CASCADE, so deleting
                # a Market here previously cascade-deleted every MarketOutcome under it,
                # which in turn cascade-deleted any Bet a user had already placed against
                # one of those outcomes -- silently destroying placed bets (and orphaning
                # their BetTicket) on every single odds-refresh cycle, not just settling
                # them late. update_or_create keeps the same Market/MarketOutcome rows
                # (and thus the same ids Bet.market_outcome points at) across refreshes.
                market, _ = Market.objects.update_or_create(
                    fixture=fixture,
                    bookmaker=bookmaker,
                    api_market_key=api_market_key,
                    defaults={
                        'category': category,
                        'last_updated_odds_api': timezone.now(),
                        'is_active': True,
                    }
                )
                total_markets_created += 1
                seen_market_ids.add(market.id)

                # Process outcomes (values)
                seen_outcome_ids = set()
                for value_data in bet_data.get('values', []):
                    outcome_value = value_data.get('value')
                    odd = value_data.get('odd')
                    
                    if outcome_value and odd:
                        try:
                            outcome_name, point_value = _parse_outcome_name_and_point(
                                api_market_key, outcome_value, fixture
                            )

                            # update_or_create rather than always inserting a fresh row --
                            # keeps the same MarketOutcome id (and thus keeps any existing
                            # Bet.market_outcome pointing at it valid) across refreshes,
                            # just updating its odds in place. Settlement reads
                            # MarketOutcome.result_status, not .odds, and a Bet's payout
                            # (potential_winnings) is computed and stored on the Bet itself
                            # at placement time -- so updating odds here never retroactively
                            # changes an already-placed bet's payout.
                            outcome = upsert_market_outcome(
                                market, outcome_name, point_value, Decimal(str(odd))
                            )
                            seen_outcome_ids.add(outcome.id)
                            total_outcomes_created += 1
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Could not parse odd value: {odd}, error: {e}")

                if seen_outcome_ids:
                    logger.debug(f"Upserted market '{bet_name}' with {len(seen_outcome_ids)} outcomes for bookmaker {bookmaker_name}")
                else:
                    logger.warning(f"No valid outcomes upserted for market '{bet_name}' from bookmaker {bookmaker_name}")

                # Outcomes that existed before this refresh but weren't present in this
                # response (e.g. the bookmaker dropped that specific line) are deactivated,
                # not deleted -- hides them from new bets while leaving any placed Bet
                # referencing them, and their settlement history, intact.
                market.outcomes.exclude(id__in=seen_outcome_ids).update(is_active=False)

    # A market a bookmaker no longer offers at all (not just one outcome within
    # a market that's still offered) never gets touched by the loop above, so it
    # would otherwise stay is_active=True forever with odds that can never
    # change again -- deactivate it here instead.
    for bookmaker_id, seen_market_ids in seen_market_ids_by_bookmaker_id.items():
        Market.objects.filter(
            fixture=fixture, bookmaker_id=bookmaker_id
        ).exclude(id__in=seen_market_ids).update(is_active=False)

    logger.info(f"✓ Odds processing complete for fixture {fixture.id}: {bookmakers_encountered} bookmakers ({bookmakers_created} new), {total_markets_created} markets, {total_outcomes_created} outcomes")


def _process_api_football_v3_live_odds_data(fixture: FootballFixture, live_odds_entry: dict):
    """
    Processes one fixture's worth of in-play odds from GET /odds/live and
    upserts it the same way _process_api_football_v3_odds_data does for
    pre-match odds -- same Market/MarketOutcome upsert-in-place semantics
    (never delete-and-recreate, for the same cascade-delete-destroys-placed-
    bets reason), same category/outcome-name mapping (via the shared
    _map_bet_to_category_and_key / _parse_outcome_name_and_point helpers).

    The one real difference: live odds carry a provider-set per-outcome
    "suspended" flag (true around live events -- goals, cards, VAR reviews,
    etc., while the provider's own pricing is momentarily unreliable).
    upsert_market_outcome's is_active is set from that flag directly, so a
    suspended outcome is immediately excluded from both the browse/outcome
    list (which only ever shows is_active=True outcomes) and bet placement
    (process_bet_ticket_submission only accepts is_active=True outcome ids)
    -- no separate suspension mechanism needed.

    /odds/live's response shape nests each bookmaker's markets under "odds"
    rather than pre-match /odds's "bookmakers" key; both are checked
    defensively in case the provider's shape shifts.
    """
    bookmakers_list = live_odds_entry.get('odds') or live_odds_entry.get('bookmakers') or []
    if not bookmakers_list:
        return

    seen_market_ids_by_bookmaker_id = {}

    for bookmaker_data in bookmakers_list:
        bookmaker_name = bookmaker_data.get('name', 'Unknown')
        bookmaker_id = bookmaker_data.get('id')
        bookmaker, _ = Bookmaker.objects.get_or_create(
            api_bookmaker_key=str(bookmaker_id) if bookmaker_id else bookmaker_name.lower().replace(' ', '_'),
            defaults={'name': bookmaker_name}
        )
        seen_market_ids = seen_market_ids_by_bookmaker_id.setdefault(bookmaker.id, set())

        for bet_data in bookmaker_data.get('bets', []):
            bet_name = bet_data.get('name', 'Unknown Market')
            bet_id = bet_data.get('id')
            category, api_market_key = _map_bet_to_category_and_key(bet_name, bet_id)

            market, _ = Market.objects.update_or_create(
                fixture=fixture,
                bookmaker=bookmaker,
                api_market_key=api_market_key,
                defaults={
                    'category': category,
                    'last_updated_odds_api': timezone.now(),
                    'is_active': True,
                }
            )
            seen_market_ids.add(market.id)

            seen_outcome_ids = set()
            for value_data in bet_data.get('values', []):
                outcome_value = value_data.get('value')
                odd = value_data.get('odd')
                if not (outcome_value and odd):
                    continue
                try:
                    outcome_name, point_value = _parse_outcome_name_and_point(
                        api_market_key, outcome_value, fixture
                    )
                    suspended = bool(value_data.get('suspended', False))
                    outcome = upsert_market_outcome(
                        market, outcome_name, point_value, Decimal(str(odd)),
                        is_active=not suspended,
                    )
                    seen_outcome_ids.add(outcome.id)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Live odds: could not parse odd value: {odd}, error: {e}")

            # An outcome missing from this live-odds tick (not just flagged
            # suspended -- genuinely absent) is deactivated the same way the
            # pre-match pipeline does, not deleted.
            market.outcomes.exclude(id__in=seen_outcome_ids).update(is_active=False)

    for bookmaker_id, seen_market_ids in seen_market_ids_by_bookmaker_id.items():
        Market.objects.filter(
            fixture=fixture, bookmaker_id=bookmaker_id
        ).exclude(id__in=seen_market_ids).update(is_active=False)


def _refresh_live_scores(client: APIFootballV3Client, live_fixtures: List[FootballFixture]) -> None:
    """Keep home/away score and elapsed match-minute fresh for currently-LIVE
    fixtures at the same per-minute cadence as their odds. Without this, the
    "LIVE 1-0" a bettor sees next to freshly-refreshed odds could still be
    up to 5 minutes stale (score/status transitions are otherwise only
    refreshed by run_score_and_settlement_v3_task on its own 5-minute
    schedule).

    Uses one GET /fixtures?live=all call -- cheap (score/status only, not
    full odds trees) and provider-side already covers every live fixture
    worldwide in a single request, unlike /odds/live's much heavier payload.
    Only touches score/elapsed here; LIVE -> FINISHED transitions and
    settlement dispatch stay owned exclusively by the 5-minute pipeline so
    there's one single place that ever triggers settlement.
    """
    try:
        live_from_api = client.get_live_fixtures()
    except Exception as e:
        logger.warning(f"_refresh_live_scores: get_live_fixtures() failed: {e}")
        return
    if not live_from_api:
        return

    info_by_api_id = {}
    for entry in live_from_api:
        api_fixture_id = entry.get('fixture', {}).get('id')
        if api_fixture_id:
            info_by_api_id[f"v3_{api_fixture_id}"] = entry

    to_update = []
    for fixture in live_fixtures:
        entry = info_by_api_id.get(fixture.api_id)
        if not entry:
            continue
        goals = entry.get('goals') or {}
        status_info = entry.get('fixture', {}).get('status') or {}
        try:
            home = int(goals['home']) if goals.get('home') is not None else None
        except (TypeError, ValueError):
            home = None
        try:
            away = int(goals['away']) if goals.get('away') is not None else None
        except (TypeError, ValueError):
            away = None
        try:
            elapsed = int(status_info['elapsed']) if status_info.get('elapsed') is not None else None
        except (TypeError, ValueError):
            elapsed = None

        changed = False
        if home is not None and fixture.home_team_score != home:
            fixture.home_team_score = home
            changed = True
        if away is not None and fixture.away_team_score != away:
            fixture.away_team_score = away
            changed = True
        if elapsed is not None and fixture.elapsed_minutes != elapsed:
            fixture.elapsed_minutes = elapsed
            changed = True
        if changed:
            fixture.last_score_update = timezone.now()
            to_update.append(fixture)

    if to_update:
        FootballFixture.objects.bulk_update(
            to_update, ['home_team_score', 'away_team_score', 'elapsed_minutes', 'last_score_update']
        )
        logger.info(f"_refresh_live_scores: updated the score for {len(to_update)} live fixture(s).")


@shared_task(name="football_data_app.fetch_live_odds_v3", queue='cpu_heavy')
def fetch_live_odds_v3_task():
    """
    Refreshes in-play odds (and, alongside them, the live score) for every
    fixture currently LIVE that already has at least one market (i.e. was
    bettable pre-match, so it's worth keeping priced through kick-off).
    Cheap early-exit when nothing is live, so this can run on a short Celery
    Beat interval without wasting API credits on every tick -- see
    fetch-live-football-odds-v3 in CELERY_BEAT_SCHEDULE.

    Fetches GET /odds/live per fixture (?fixture=<id>), keyed to the exact
    fixtures we hold open markets for, rather than one global bulk call: the
    unfiltered bulk response covers every live match worldwide the provider
    has odds for, the vast majority of which aren't fixtures we ever opened
    for betting, so it wastes bandwidth/parse time on data we'd throw away
    and (on providers that page or cap that response) risks silently missing
    one of ours. A handful of live fixtures easily fits the 300 req/min rate
    limit the client already enforces per-request.
    """
    live_fixtures = list(
        FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.LIVE,
            api_id__startswith='v3_',
            markets__isnull=False,
        ).distinct()
    )
    if not live_fixtures:
        logger.debug("fetch_live_odds_v3_task: no live fixtures with existing markets, skipping.")
        return

    client = APIFootballV3Client()
    _refresh_live_scores(client, live_fixtures)

    processed = 0
    for fixture in live_fixtures:
        try:
            api_fixture_id = int(fixture.api_id.replace('v3_', '', 1))
        except (TypeError, ValueError):
            logger.warning(f"fetch_live_odds_v3_task: fixture {fixture.id} has a malformed api_id {fixture.api_id!r}, skipping.")
            continue

        try:
            live_odds = client.get_live_odds(fixture_id=api_fixture_id)
        except Exception as e:
            logger.error(f"fetch_live_odds_v3_task: get_live_odds(fixture_id={api_fixture_id}) failed: {e}", exc_info=True)
            continue

        if not live_odds:
            continue

        for entry in live_odds:
            _process_api_football_v3_live_odds_data(fixture, entry)
        processed += 1

    logger.info(f"fetch_live_odds_v3_task: refreshed live odds for {processed}/{len(live_fixtures)} fixture(s).")


# --- PIPELINE 1: Full Data Update (Leagues, Events, Odds) ---

@shared_task(name="football_data_app.run_api_football_v3_full_update", queue='cpu_heavy')
def run_api_football_v3_full_update_task():
    """Main entry point for the API-Football v3 data fetching pipeline."""
    logger.info("="*80)
    logger.info("TASK START: run_api_football_v3_full_update_task")
    logger.info("="*80)
    try:
        pipeline = (
            fetch_and_update_leagues_v3_task.s() |
            _prepare_and_launch_event_odds_chord_v3.s()
        )
        result = pipeline.apply_async()
        logger.info(f"Pipeline scheduled successfully with ID: {result.id if hasattr(result, 'id') else 'N/A'}")
        logger.info("TASK END: run_api_football_v3_full_update_task - Pipeline dispatched")
        return {"status": "dispatched", "pipeline_id": str(result.id) if hasattr(result, 'id') else None}
    except Exception as e:
        logger.error(f"TASK ERROR: run_api_football_v3_full_update_task failed with error: {e}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300, queue='cpu_heavy')
def fetch_and_update_leagues_v3_task(self, _=None):
    """Step 1: Fetches all available football leagues from API-Football v3."""
    logger.info("="*80)
    logger.info("TASK START: fetch_and_update_leagues_v3_task (League Update Pipeline)")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    client = APIFootballV3Client()
    
    try:
        logger.info("Calling APIFootballV3Client.get_leagues()...")
        leagues_data = client.get_leagues()
        
        if not leagues_data:
            logger.warning("No leagues data received from API-Football v3 API.")
            logger.info("TASK END: fetch_and_update_leagues_v3_task - No data")
            return []
        
        logger.info(f"Received {len(leagues_data)} leagues from API-Football v3 API")
        
        processed_league_ids = []
        created_count = 0
        updated_count = 0
        
        for idx, league_item in enumerate(leagues_data, 1):
            league_id = league_item.get('league', {}).get('id')
            league_name = league_item.get('league', {}).get('name')
            country_name = league_item.get('country', {}).get('name')
            league_logo = league_item.get('league', {}).get('logo')
            
            if not league_id or not league_name:
                logger.warning(f"Skipping league {idx} - missing league ID or name")
                continue
            
            # Store the league with v3_ prefix to distinguish from legacy
            api_id_str = f"v3_{league_id}"
            
            league_obj, created = League.objects.update_or_create(
                api_id=api_id_str,
                defaults={
                    'name': league_name,
                    'sport_key': 'soccer',
                    'sport_group_name': 'Football',
                    'short_name': league_name,
                    'country_name': country_name,
                    'logo_url': league_logo,
                    'active': True
                }
            )
            
            processed_league_ids.append(league_obj.id)
            
            if created:
                created_count += 1
                logger.info(f"Created new league: {league_name} (API ID: {league_id}, DB ID: {league_obj.id})")
            else:
                updated_count += 1
                logger.debug(f"Updated existing league: {league_name} (API ID: {league_id}, DB ID: {league_obj.id})")
        
        logger.info(f"League processing complete: {len(processed_league_ids)} total, {created_count} created, {updated_count} updated")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_and_update_leagues_v3_task - SUCCESS")
        logger.info(f"Returning {len(processed_league_ids)} league IDs to next task")
        logger.info("="*80)
        return processed_league_ids
        
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error during league update: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error during league update: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)


@shared_task(name="football_data_app._prepare_and_launch_event_odds_chord_v3", queue='cpu_heavy')
def _prepare_and_launch_event_odds_chord_v3(league_ids: List[int]):
    """
    Intermediate task: Receives league_ids and launches event fetching chord.
    """
    logger.info("="*80)
    logger.info("TASK START: _prepare_and_launch_event_odds_chord_v3")
    logger.info("="*80)
    
    if not league_ids:
        logger.warning("="*80)
        logger.warning("No league IDs received from previous task. Skipping event/odds processing.")
        logger.warning("")
        logger.warning("This usually means:")
        logger.warning("1. No leagues exist in the database yet, OR")
        logger.warning("2. The league fetch from API-Football v3 returned no results")
        logger.warning("")
        logger.warning("FIRST-TIME SETUP: If this is your first run, ensure you have:")
        logger.warning("1. A valid API-Football v3 API key configured")
        logger.warning(f"2. Run: {LEAGUE_SETUP_COMMAND}")
        logger.warning("")
        logger.warning("The fetch_and_update_leagues_v3_task should have populated leagues automatically.")
        logger.warning("Check the logs above for any API errors or authentication issues.")
        logger.warning("="*80)
        logger.info("TASK END: _prepare_and_launch_event_odds_chord_v3 - No leagues to process")
        return
    
    logger.info(f"Received {len(league_ids)} league IDs from previous task: {league_ids}")
    logger.info(f"Preparing to fetch events for {len(league_ids)} leagues...")
    
    try:
        event_fetch_tasks_group = group([
            fetch_events_for_league_v3_task.s(league_id) for league_id in league_ids
        ])
        
        odds_dispatch_callback = dispatch_odds_fetching_after_events_v3_task.s()
        
        logger.info(f"Creating chord with {len(league_ids)} event fetch tasks...")
        task_chord = chord(event_fetch_tasks_group)(odds_dispatch_callback)
        result = task_chord.apply_async()
        
        logger.info(f"Chord dispatched successfully. Chord ID: {result.id if hasattr(result, 'id') else 'N/A'}")
        logger.info(f"Event fetch tasks will execute in parallel for {len(league_ids)} leagues")
        logger.info("After all event fetches complete, odds dispatch task will be triggered")
        logger.info("="*80)
        logger.info("TASK END: _prepare_and_launch_event_odds_chord_v3 - SUCCESS")
        logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Failed to create or dispatch chord: {e}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=600, queue='cpu_heavy')
def fetch_events_for_league_v3_task(self, league_id: int):
    """Fetches and updates events (fixtures) for a single league from API-Football v3."""
    logger.info("="*80)
    logger.info(f"TASK START: fetch_events_for_league_v3_task - League ID: {league_id}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    events_processed_count = 0
    
    try:
        logger.info(f"Fetching league from database (ID: {league_id})...")
        league = League.objects.get(id=league_id)
        logger.info(f"League found: {league.name} (API ID: {league.api_id})")
        
        # Extract the numeric ID from v3_ prefix
        if not league.api_id.startswith('v3_'):
            logger.warning(f"League {league_id} does not have v3_ prefix, skipping")
            return {"league_id": league_id, "status": "skipped", "message": "Not a v3 league"}
        
        api_league_id = int(league.api_id.replace('v3_', ''))
        
        client = APIFootballV3Client()
        
        # Calculate date range for upcoming fixtures
        from_date = datetime.now()
        to_date = from_date + timedelta(days=API_FOOTBALL_V3_LEAD_TIME_DAYS)
        
        # Get current season from Configuration or settings
        current_season = get_current_season()
        
        logger.info(f"Calling APIFootballV3Client.get_fixtures(league_id={api_league_id}, season={current_season}, date_from={from_date.date()}, date_to={to_date.date()})...")
        fixtures_data = client.get_fixtures(
            league_id=api_league_id,
            season=current_season,
            date_from=from_date.strftime('%Y-%m-%d'),
            date_to=to_date.strftime('%Y-%m-%d')
        )
        
        logger.info(f"API returned {len(fixtures_data) if fixtures_data else 0} fixtures for league {league.name}")
        
        fixture_ids_for_odds = []  # Track fixtures that need odds fetching
        
        if fixtures_data:
            logger.info(f"Processing {len(fixtures_data)} fixtures for league {league.name}...")
            with transaction.atomic():
                for idx, fixture_item in enumerate(fixtures_data, 1):
                    fixture_info = fixture_item.get('fixture', {})
                    teams_info = fixture_item.get('teams', {})
                    goals_info = fixture_item.get('goals', {})
                    
                    fixture_id = fixture_info.get('id')
                    fixture_timestamp = fixture_info.get('date')
                    fixture_status = fixture_info.get('status', {}).get('short', '')
                    
                    home_team_data = teams_info.get('home', {})
                    away_team_data = teams_info.get('away', {})
                    
                    home_team_name = home_team_data.get('name')
                    away_team_name = away_team_data.get('name')
                    home_team_id = home_team_data.get('id')
                    away_team_id = away_team_data.get('id')
                    home_team_logo = home_team_data.get('logo')
                    away_team_logo = away_team_data.get('logo')
                    
                    if not fixture_id or not home_team_name or not away_team_name:
                        logger.warning(f"Skipping fixture {idx} - missing required data")
                        continue
                    
                    # Create or get teams
                    home_team, home_created = Team.objects.get_or_create(
                        name=home_team_name,
                        defaults={
                            'api_team_id': f"v3_{home_team_id}" if home_team_id else None,
                            'logo_url': home_team_logo
                        }
                    )
                    if home_created:
                        logger.debug(f"Created new team: {home_team_name}")
                    
                    away_team, away_created = Team.objects.get_or_create(
                        name=away_team_name,
                        defaults={
                            'api_team_id': f"v3_{away_team_id}" if away_team_id else None,
                            'logo_url': away_team_logo
                        }
                    )
                    if away_created:
                        logger.debug(f"Created new team: {away_team_name}")
                    
                    # Parse match datetime
                    match_datetime = parse_api_football_v3_datetime(fixture_timestamp)
                    
                    # Determine fixture status
                    status_map = {
                        'NS': FootballFixture.FixtureStatus.SCHEDULED,  # Not Started
                        'TBD': FootballFixture.FixtureStatus.SCHEDULED,  # Time To Be Defined
                        'LIVE': FootballFixture.FixtureStatus.LIVE,
                        '1H': FootballFixture.FixtureStatus.LIVE,  # First Half
                        'HT': FootballFixture.FixtureStatus.LIVE,  # Halftime
                        '2H': FootballFixture.FixtureStatus.LIVE,  # Second Half
                        'ET': FootballFixture.FixtureStatus.LIVE,  # Extra Time
                        'P': FootballFixture.FixtureStatus.LIVE,  # Penalty
                        'FT': FootballFixture.FixtureStatus.FINISHED,  # Full Time
                        'AET': FootballFixture.FixtureStatus.FINISHED,  # After Extra Time
                        'PEN': FootballFixture.FixtureStatus.FINISHED,  # After Penalty
                        'PST': FootballFixture.FixtureStatus.POSTPONED,
                        'CANC': FootballFixture.FixtureStatus.CANCELLED,
                        'ABD': FootballFixture.FixtureStatus.CANCELLED,  # Abandoned
                    }
                    status = status_map.get(fixture_status, FootballFixture.FixtureStatus.SCHEDULED)
                    
                    # Get scores if available
                    home_score = goals_info.get('home')
                    away_score = goals_info.get('away')
                    
                    # Clean up score values
                    try:
                        home_score = int(home_score) if home_score is not None and home_score != '' else None
                    except (ValueError, TypeError):
                        home_score = None
                    
                    try:
                        away_score = int(away_score) if away_score is not None and away_score != '' else None
                    except (ValueError, TypeError):
                        away_score = None
                    
                    # Create or update fixture
                    fixture_api_id = f"v3_{fixture_id}"
                    fixture, fixture_created = FootballFixture.objects.update_or_create(
                        api_id=fixture_api_id,
                        defaults={
                            'league': league,
                            'home_team': home_team,
                            'away_team': away_team,
                            'match_date': match_datetime,
                            'match_updated': timezone.now(),
                            'status': status,
                            'home_team_score': home_score,
                            'away_team_score': away_score,
                        }
                    )
                    events_processed_count += 1
                    
                    if fixture_created:
                        logger.debug(f"Created fixture: {home_team_name} vs {away_team_name} (Fixture ID: {fixture_id})")
                    else:
                        logger.debug(f"Updated fixture: {home_team_name} vs {away_team_name} (Fixture ID: {fixture_id})")
                    
                    # Add fixture to odds fetching list if it's scheduled and upcoming
                    if status == FootballFixture.FixtureStatus.SCHEDULED and match_datetime:
                        fixture_ids_for_odds.append(fixture.id)
            
            logger.info(f"Successfully processed {events_processed_count} fixtures in database transaction")

            # Odds are no longer fetched here per-fixture. They are fetched in
            # bulk per league-day by dispatch_odds_fetching_after_events_v3_task
            # (the chord callback), which runs once after all leagues' events are
            # in and de-duplicates via last_odds_update staleness — far fewer API
            # requests and no double-fetch race.
            if fixture_ids_for_odds:
                logger.info(f"{len(fixture_ids_for_odds)} scheduled fixture(s) will get bulk odds via the odds-dispatch callback.")

        # Update league's last fetch timestamp
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Updated league.last_fetched_events timestamp for {league.name}")
        
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_v3_task - SUCCESS")
        logger.info(f"League: {league.name}, Events Processed: {events_processed_count}")
        logger.info("="*80)
        return {"league_id": league_id, "status": "success", "events_processed": events_processed_count}
        
    except League.DoesNotExist:
        logger.error(f"TASK ERROR: League with ID {league_id} does not exist in database")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_v3_task - FAILED (League not found)")
        logger.info("="*80)
        return {"league_id": league_id, "status": "error", "message": "League not found"}
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error for league {league_id}: {e}", exc_info=True)
        if self.request.retries >= self.max_retries:
            # This task runs inside a chord alongside every other league (see
            # _prepare_and_launch_event_odds_chord_v3): letting the exception
            # propagate here after retries are exhausted would mark this task
            # FAILURE, which breaks the whole chord silently and means
            # dispatch_odds_fetching_after_events_v3_task -- the only place
            # odds ever get dispatched -- never runs for the entire cycle.
            # Degrade to an error result instead so the chord can still complete.
            logger.error(f"Max retries exceeded for league {league_id}; giving up without breaking the odds-dispatch chord.")
            logger.info("="*80)
            logger.info(f"TASK END: fetch_events_for_league_v3_task - FAILED (max retries exceeded)")
            logger.info("="*80)
            return {"league_id": league_id, "status": "error", "message": str(e)}
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error fetching events for league {league_id}: {e}", exc_info=True)
        logger.info("="*80)
        logger.info(f"TASK END: fetch_events_for_league_v3_task - FAILED")
        logger.info("="*80)
        return {"league_id": league_id, "status": "error", "message": str(e)}


@shared_task(bind=True, name="football_data_app.dispatch_odds_fetching_after_events_v3", queue='cpu_heavy')
def dispatch_odds_fetching_after_events_v3_task(self, results_from_event_fetches=None):
    """
    Dispatches individual tasks to fetch odds for each upcoming fixture that
    needs one, based purely on DB staleness (see the query below) -- it does
    not actually depend on `results_from_event_fetches` for that decision, so
    this task is safe to run either as the events-fetch chord's callback, or
    entirely standalone from its own periodic schedule (see
    CELERY_BEAT_SCHEDULE['dispatch-football-odds-v3']).

    The standalone schedule exists because CELERY_RESULT_BACKEND='django-db'
    does not natively support chords (no atomic increment backend); Celery
    falls back to a polling "chord_unlock" task which is fragile at the scale
    of this chord (700+ leagues per header) and can end up never invoking this
    callback at all, silently starving odds fetching indefinitely even though
    every individual league's events keep updating fine. Running this on its
    own schedule guarantees odds still get dispatched regardless of whether
    the chord ever completes.
    """
    logger.info("="*80)
    logger.info("TASK START: dispatch_odds_fetching_after_events_v3_task (Odds Dispatch)")
    logger.info(f"Task ID: {self.request.id}")
    logger.info("="*80)

    results_from_event_fetches = results_from_event_fetches or []
    logger.info(f"Received {len(results_from_event_fetches)} result(s) from event fetching group")
    logger.debug(f"Event fetch results: {results_from_event_fetches}")

    # Count successful events
    total_events_processed = 0
    for result in results_from_event_fetches:
        if isinstance(result, dict) and result.get('status') == 'success':
            total_events_processed += result.get('events_processed', 0)
    logger.info(f"Total events processed across all leagues: {total_events_processed}")
    
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES)
    
    logger.info(f"Querying fixtures that need odds updates...")
    logger.info(f"Criteria: SCHEDULED status, match_date in next {API_FOOTBALL_V3_LEAD_TIME_DAYS} days, odds older than {API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES} minutes")
    
    # Fixtures needing odds, with the (league, day) they belong to. Odds are
    # fetched in bulk per league-day, so we only need the distinct pairs — not
    # one task per fixture.
    fixtures_needing_odds = FootballFixture.objects.filter(
        models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=stale_cutoff),
        status=FootballFixture.FixtureStatus.SCHEDULED,
        match_date__range=(now, now + timedelta(days=API_FOOTBALL_V3_LEAD_TIME_DAYS)),
        api_id__startswith='v3_'  # Only v3 fixtures
    ).values_list('league_id', 'match_date')

    # Group by the fixture's UTC day: fixtures are ingested with timezone=UTC and
    # the /odds `date` filter is likewise evaluated in UTC (the client sends no
    # timezone), so a UTC day keeps the bulk query aligned with what we stored.
    league_day_pairs = set()
    for league_id, match_date in fixtures_needing_odds:
        if match_date:
            utc_day = timezone.localtime(match_date, dt_timezone.utc).strftime('%Y-%m-%d')
            league_day_pairs.add((league_id, utc_day))

    fixture_count = len(fixtures_needing_odds)
    logger.info(f"Fixtures needing odds update: {fixture_count} across {len(league_day_pairs)} league-day group(s)")

    if not league_day_pairs:
        logger.info("No fixtures require an odds update at this time.")
        logger.info("="*80)
        logger.info("TASK END: dispatch_odds_fetching_after_events_v3_task - No odds updates needed")
        logger.info("="*80)
        return

    # One bulk request-set per league-day instead of one request per fixture.
    tasks = [fetch_odds_for_league_date_v3_task.s(league_id, day) for league_id, day in league_day_pairs]
    group(tasks).apply_async()
    logger.info(f"Dispatched {len(tasks)} bulk odds task(s) for {fixture_count} fixtures "
                f"(was 1 task/fixture; now 1 task/league-day).")
    logger.info("="*80)
    logger.info("TASK END: dispatch_odds_fetching_after_events_v3_task - SUCCESS")
    logger.info("="*80)


@shared_task(bind=True, max_retries=2, default_retry_delay=300, queue='cpu_heavy')
def fetch_odds_for_single_event_v3_task(self, fixture_id: int):
    """Fetches odds for a single fixture from API-Football v3."""
    # Add jitter to spread out API requests
    jitter_delay = random.uniform(0.5, 3.0)
    logger.debug(f"Applying jitter delay of {jitter_delay:.2f}s before fetching odds for fixture {fixture_id}")
    time.sleep(jitter_delay)
    
    logger.info(f"TASK START: fetch_odds_for_single_event_v3_task - Fixture ID: {fixture_id}")
    
    try:
        logger.debug(f"Fetching fixture {fixture_id} from database...")
        fixture = FootballFixture.objects.select_related('league', 'home_team', 'away_team').get(id=fixture_id)
        logger.info(f"Fetching odds for: {fixture.home_team.name} vs {fixture.away_team.name} (API ID: {fixture.api_id})")
        
        # Extract numeric fixture ID from v3_ prefix
        if not fixture.api_id or not fixture.api_id.startswith('v3_'):
            logger.warning(f"Fixture {fixture_id} is not a v3 fixture, skipping")
            return {"fixture_id": fixture_id, "status": "skipped"}
        
        api_fixture_id = int(fixture.api_id.replace('v3_', ''))
        
        client = APIFootballV3Client()
        
        logger.debug(f"Calling APIFootballV3Client.get_odds(fixture_id={api_fixture_id})...")
        odds_data = client.get_odds(fixture_id=api_fixture_id)
        
        logger.info(f"API returned {len(odds_data) if odds_data else 0} odds items for fixture {fixture.id}")
        
        if not odds_data:
            logger.info(f"No odds data returned from API for fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name})")
            fixture.last_odds_update = timezone.now()
            fixture.save(update_fields=['last_odds_update'])
            logger.info(f"TASK END: fetch_odds_for_single_event_v3_task - No odds available")
            return {"fixture_id": fixture.id, "status": "no_odds_data"}
        
        logger.info(f"Processing odds data for fixture {fixture.id}...")
        with transaction.atomic():
            fixture_for_update = FootballFixture.objects.select_for_update().get(id=fixture.id)
            
            # Process odds data
            _process_api_football_v3_odds_data(fixture_for_update, odds_data)
            
            fixture_for_update.last_odds_update = timezone.now()
            fixture_for_update.save(update_fields=['last_odds_update'])
            
            logger.info(f"Successfully processed and saved odds for fixture {fixture.id}")
            logger.info(f"TASK END: fetch_odds_for_single_event_v3_task - SUCCESS (Fixture: {fixture.id})")
            return {"fixture_id": fixture.id, "status": "success"}
    
    except FootballFixture.DoesNotExist:
        logger.error(f"TASK ERROR: Fixture with ID {fixture_id} not found in database")
        logger.info(f"TASK END: fetch_odds_for_single_event_v3_task - FAILED (Fixture not found)")
        return {"fixture_id": fixture_id, "status": "error", "message": "Fixture not found"}
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error for fixture {fixture_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error for fixture {fixture_id}: {e}", exc_info=True)
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=300, queue='cpu_heavy')
def fetch_odds_for_league_date_v3_task(self, league_pk: int, date_str: str):
    """
    Fetch odds in bulk for every fixture of one league on one day.

    API-Football's /odds endpoint returns odds for many fixtures when queried by
    league + season + date (paginated at 10 per page). This replaces the old
    one-request-per-fixture approach: a league-day with N fixtures now costs a
    couple of paginated requests instead of N requests — a large quota saving.
    """
    jitter_delay = random.uniform(0.5, 2.0)
    time.sleep(jitter_delay)
    logger.info(f"TASK START: fetch_odds_for_league_date_v3_task - league_pk={league_pk}, date={date_str}")

    try:
        league = League.objects.get(id=league_pk)
        if not league.api_id or not league.api_id.startswith('v3_'):
            logger.warning(f"League {league_pk} is not a v3 league; skipping bulk odds.")
            return {"league_pk": league_pk, "date": date_str, "status": "skipped"}
        api_league_id = int(league.api_id.replace('v3_', ''))
        season = get_current_season()

        client = APIFootballV3Client()
        odds_items = client.get_odds(
            league_id=api_league_id,
            season=season,
            date=date_str,
            paginate=True,
            max_pages=API_FOOTBALL_V3_MAX_ODDS_PAGES,
        )
        logger.info(f"Bulk odds returned {len(odds_items)} item(s) for league '{league.name}' on {date_str}")

        # Group the bulk response by API fixture id.
        items_by_fixture = {}
        for item in odds_items:
            fid = (item.get('fixture') or {}).get('id')
            if fid is not None:
                items_by_fixture.setdefault(int(fid), []).append(item)

        if not items_by_fixture:
            logger.info(f"No odds available for league '{league.name}' on {date_str}.")
            return {"league_pk": league_pk, "date": date_str, "status": "no_odds", "fixtures": 0}

        # Map our stored fixtures for this league-day in one query.
        api_ids = [f"v3_{fid}" for fid in items_by_fixture.keys()]
        fixtures = {
            int(f.api_id.replace('v3_', '')): f
            for f in FootballFixture.objects.filter(api_id__in=api_ids)
        }

        processed = 0
        for api_fid, items in items_by_fixture.items():
            fixture = fixtures.get(api_fid)
            if not fixture:
                continue  # Odds for a fixture we don't track; ignore.
            try:
                with transaction.atomic():
                    fixture_for_update = FootballFixture.objects.select_for_update().get(id=fixture.id)
                    _process_api_football_v3_odds_data(fixture_for_update, items)
                    fixture_for_update.last_odds_update = timezone.now()
                    fixture_for_update.save(update_fields=['last_odds_update'])
                processed += 1
            except Exception as e:
                logger.error(f"Failed to process bulk odds for fixture {fixture.id}: {e}", exc_info=True)

        logger.info(f"TASK END: fetch_odds_for_league_date_v3_task - processed odds for {processed} fixture(s)")
        return {"league_pk": league_pk, "date": date_str, "status": "success", "fixtures": processed}

    except League.DoesNotExist:
        logger.error(f"League {league_pk} not found for bulk odds fetch.")
        return {"league_pk": league_pk, "date": date_str, "status": "error", "message": "League not found"}
    except APIFootballV3Exception as e:
        logger.error(f"API-Football v3 error during bulk odds fetch (league {league_pk}, {date_str}): {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Unexpected error during bulk odds fetch (league {league_pk}, {date_str}): {e}", exc_info=True)
        raise self.retry(exc=e)


# --- PIPELINE 2: Score Fetching and Settlement ---

@shared_task(name="football_data_app.run_score_and_settlement_v3_task", queue='cpu_heavy')
def run_score_and_settlement_v3_task():
    """Entry point for fetching scores and updating statuses using API-Football v3."""
    logger.info("="*80)
    logger.info("TASK START: run_score_and_settlement_v3_task (Score & Settlement Pipeline)")
    logger.info("="*80)
    
    try:
        logger.info("Fetching active v3 leagues from database...")
        active_leagues = League.objects.filter(active=True, api_id__startswith='v3_').values_list('id', flat=True)
        league_count = len(active_leagues)
        
        logger.info(f"Found {league_count} active API-Football v3 leagues")
        
        if not league_count:
            logger.warning("="*80)
            logger.warning("No active API-Football v3 leagues found. Skipping score fetching.")
            logger.warning("")
            logger.warning("FIRST-TIME SETUP REQUIRED:")
            logger.warning("To initialize football leagues, run this command:")
            logger.warning(f"  {LEAGUE_SETUP_COMMAND_DOCKER}")
            logger.warning("")
            logger.warning("Or from within the container:")
            logger.warning(f"  {LEAGUE_SETUP_COMMAND}")
            logger.warning("")
            logger.warning("This fetches available leagues from API-Football v3 and populates the database.")
            logger.warning("Without this, no betting data can be fetched or processed.")
            logger.warning("="*80)
            logger.info("TASK END: run_score_and_settlement_v3_task - No active leagues")
            return
        
        logger.info(f"Creating {league_count} score fetching tasks (one per league)...")
        tasks = [fetch_scores_for_league_v3_task.s(league_id) for league_id in active_leagues]
        
        if tasks:
            group(tasks).apply_async()
            logger.info(f"Successfully dispatched {len(tasks)} score fetching tasks to the queue")
            logger.info("="*80)
            logger.info("TASK END: run_score_and_settlement_v3_task - SUCCESS")
            logger.info(f"Dispatched {len(tasks)} tasks")
            logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Failed to dispatch score fetching tasks: {e}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=900, queue='cpu_heavy')
def fetch_scores_for_league_v3_task(self, league_id: int):
    """
    Fetches live and finished match scores for a league from API-Football v3.
    """
    logger.info("="*80)
    logger.info(f"TASK START: fetch_scores_for_league_v3_task - League ID: {league_id}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    now = timezone.now()
    assumed_completion_cutoff = now - timedelta(minutes=API_FOOTBALL_V3_ASSUMED_COMPLETION_MINUTES)
    
    try:
        logger.debug(f"Fetching league {league_id} from database...")
        league = League.objects.get(id=league_id)
        logger.info(f"Processing scores for league: {league.name} (API ID: {league.api_id})")
        
        # Extract numeric league ID
        if not league.api_id.startswith('v3_'):
            logger.warning(f"League {league_id} is not a v3 league, skipping")
            return
        
        api_league_id = int(league.api_id.replace('v3_', ''))
        
        # Get fixtures that need score updates (live or recently started)
        logger.debug("Querying fixtures that need score updates...")
        fixtures_to_check_qs = FootballFixture.objects.filter(
            league=league,
            api_id__startswith='v3_'
        ).filter(
            models.Q(status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(
                status=FootballFixture.FixtureStatus.SCHEDULED,
                match_date__lt=now
            )
        )
        
        fixture_count = fixtures_to_check_qs.count()
        logger.info(f"Found {fixture_count} fixtures requiring score updates (LIVE or past SCHEDULED)")
        
        if not fixtures_to_check_qs.exists():
            logger.info(f"No fixtures need a score update for league {league.name}.")
            logger.info("="*80)
            logger.info("TASK END: fetch_scores_for_league_v3_task - No updates needed")
            logger.info("="*80)
            return
        
        client = APIFootballV3Client()
        
        logger.info(f"Calling APIFootballV3Client.get_live_fixtures()...")
        live_fixtures = client.get_live_fixtures()
        logger.info(f"Received {len(live_fixtures) if live_fixtures else 0} live fixtures from API")
        
        # Get current season from Configuration or settings
        current_season = get_current_season()
        
        # Get finished matches from the past few days
        date_from = (now - timedelta(days=2)).strftime('%Y-%m-%d')
        date_to = now.strftime('%Y-%m-%d')
        logger.info(f"Calling APIFootballV3Client.get_fixtures(league_id={api_league_id}, season={current_season}, date_from={date_from}, date_to={date_to}, status=FT)...")
        finished_fixtures = client.get_fixtures(
            league_id=api_league_id,
            season=current_season,
            date_from=date_from,
            date_to=date_to,
            status='FT'  # Full Time
        )
        logger.info(f"Received {len(finished_fixtures) if finished_fixtures else 0} finished fixtures from API")
        
        # Combine live and finished fixtures
        all_fixtures = []
        if live_fixtures:
            all_fixtures.extend(live_fixtures)
        if finished_fixtures:
            all_fixtures.extend(finished_fixtures)
        
        # Filter to only fixtures from this league
        league_fixtures = [f for f in all_fixtures if f.get('league', {}).get('id') == api_league_id]
        logger.info(f"Total fixtures for this league after filtering: {len(league_fixtures)}")
        
        processed_api_ids = set()
        fixtures_updated = 0
        fixtures_finished = 0
        fixtures_live = 0
        
        if league_fixtures:
            logger.info(f"Processing {len(league_fixtures)} fixture updates...")
            for idx, fixture_data in enumerate(league_fixtures, 1):
                fixture_info = fixture_data.get('fixture', {})
                goals_info = fixture_data.get('goals', {})
                
                api_fixture_id = fixture_info.get('id')
                if not api_fixture_id:
                    logger.warning(f"Fixture item {idx} missing ID, skipping")
                    continue
                
                fixture_api_id_str = f"v3_{api_fixture_id}"
                processed_api_ids.add(fixture_api_id_str)
                
                try:
                    with transaction.atomic():
                        fixture = FootballFixture.objects.select_for_update().get(api_id=fixture_api_id_str)
                        
                        if fixture.status == FootballFixture.FixtureStatus.FINISHED:
                            logger.debug(f"Fixture {fixture.id} already FINISHED, skipping")
                            continue
                        
                        # Get scores
                        home_score = goals_info.get('home')
                        away_score = goals_info.get('away')
                        status_info = fixture_info.get('status', {}) or {}
                        fixture_status = status_info.get('short', '')
                        elapsed = status_info.get('elapsed')

                        # Parse scores
                        try:
                            home_score = int(home_score) if home_score is not None and home_score != '' else None
                        except (ValueError, TypeError):
                            home_score = None

                        try:
                            away_score = int(away_score) if away_score is not None and away_score != '' else None
                        except (ValueError, TypeError):
                            away_score = None

                        try:
                            elapsed = int(elapsed) if elapsed is not None else None
                        except (ValueError, TypeError):
                            elapsed = None

                        # Update scores if available
                        if home_score is not None:
                            fixture.home_team_score = home_score
                        if away_score is not None:
                            fixture.away_team_score = away_score
                        if elapsed is not None:
                            fixture.elapsed_minutes = elapsed

                        fixture.last_score_update = timezone.now()
                        fixture.match_updated = timezone.now()

                        update_fields = ['home_team_score', 'away_team_score', 'elapsed_minutes', 'status', 'last_score_update', 'match_updated']
                        
                        # Update status
                        if fixture_status in ['FT', 'AET', 'PEN']:  # Finished statuses
                            fixture.status = FootballFixture.FixtureStatus.FINISHED
                            fixture.save(update_fields=update_fields)
                            fixtures_finished += 1
                            logger.info(f"Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) marked FINISHED. Score: {home_score}-{away_score}")
                            
                            # Import settlement tasks from legacy tasks (reusable)
                            from .tasks_apifootball import settle_fixture_pipeline_task
                            logger.info(f"Triggering settlement pipeline for fixture {fixture.id}...")
                            settle_fixture_pipeline_task.delay(fixture.id)
                        elif fixture_status in ['LIVE', '1H', 'HT', '2H', 'ET', 'P']:  # Live statuses
                            fixture.status = FootballFixture.FixtureStatus.LIVE
                            fixture.save(update_fields=update_fields)
                            fixtures_live += 1
                            logger.debug(f"Fixture {fixture.id} is LIVE. Score: {home_score}-{away_score}")
                        else:
                            fixture.save(update_fields=update_fields)
                        
                        fixtures_updated += 1
                
                except FootballFixture.DoesNotExist:
                    logger.warning(f"Received score data for unknown fixture API ID: {fixture_api_id_str}")
        
        # Handle fixtures past assumed completion time
        unprocessed_fixtures = fixtures_to_check_qs.exclude(api_id__in=processed_api_ids)
        unprocessed_count = unprocessed_fixtures.count()
        
        if unprocessed_count > 0:
            logger.info(f"Checking {unprocessed_count} unprocessed fixtures for assumed completion...")
            fixtures_assumed_finished = 0
            
            for fixture in unprocessed_fixtures:
                if fixture.match_date and fixture.match_date < assumed_completion_cutoff:
                    with transaction.atomic():
                        fixture_to_finish = FootballFixture.objects.select_for_update().get(id=fixture.id)
                        
                        if fixture_to_finish.status == FootballFixture.FixtureStatus.FINISHED:
                            continue
                        
                        if fixture_to_finish.home_team_score is None:
                            fixture_to_finish.home_team_score = 0
                        if fixture_to_finish.away_team_score is None:
                            fixture_to_finish.away_team_score = 0
                        
                        fixture_to_finish.status = FootballFixture.FixtureStatus.FINISHED
                        fixture_to_finish.last_score_update = timezone.now()
                        fixture_to_finish.save(update_fields=['home_team_score', 'away_team_score', 'status', 'last_score_update'])
                        
                        fixtures_assumed_finished += 1
                        logger.warning(
                            f"Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) "
                            f"not in API response and past assumed completion time. "
                            f"Marking FINISHED with score: {fixture_to_finish.home_team_score}-{fixture_to_finish.away_team_score}"
                        )
                        
                        from .tasks_apifootball import settle_fixture_pipeline_task
                        settle_fixture_pipeline_task.delay(fixture.id)
            
            if fixtures_assumed_finished > 0:
                logger.info(f"Marked {fixtures_assumed_finished} fixtures as assumed finished")
        
        logger.info("="*80)
        logger.info(f"TASK END: fetch_scores_for_league_v3_task - SUCCESS")
        logger.info(f"League: {league.name}, Updated: {fixtures_updated}, Finished: {fixtures_finished}, Live: {fixtures_live}")
        logger.info("="*80)
    
    except League.DoesNotExist:
        logger.error(f"TASK ERROR: League {league_id} not found in database")
        logger.info("="*80)
        logger.info(f"TASK END: fetch_scores_for_league_v3_task - FAILED (League not found)")
        logger.info("="*80)
    except APIFootballV3Exception as e:
        logger.error(f"TASK ERROR: API-Football v3 API error for league {league_id}: {e}", exc_info=True)
        logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"TASK ERROR: Unexpected error fetching scores for league {league_id}: {e}", exc_info=True)
        raise self.retry(exc=e)


# --- Task Aliases for Backward Compatibility ---

@shared_task(name="football_data_app.run_api_football_v3_full_update_alias", queue='cpu_heavy')
def run_api_football_v3_full_update():
    """
    Alias for run_api_football_v3_full_update_task with a simplified name.
    """
    return run_api_football_v3_full_update_task()


@shared_task(name="football_data_app.run_score_and_settlement_v3_alias", queue='cpu_heavy')
def run_score_and_settlement_v3():
    """
    Alias for run_score_and_settlement_v3_task with a simplified name.
    """
    return run_score_and_settlement_v3_task()
