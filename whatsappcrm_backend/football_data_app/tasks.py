# football_data_app/tasks.py
import logging
from django.conf import settings
from celery import shared_task
from django.db import transaction, IntegrityError, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# --- Settings or Defaults (Broad & Frequent Configuration) ---
# These values are now more aggressive to ensure data is fresh and comprehensive.
# This will use more API credits.

# --- SCOPE EXPANSION SETTINGS ---
# Look for games 7 days in advance.
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
# Request data from multiple regions by default.
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us")
# Request all primary markets by default.
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,spreads")

# --- FREQUENCY INCREASE SETTINGS ---
# For games starting soon (e.g., in <2 hours), update odds every 15 minutes.
ODDS_IMMINENT_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_IMMINENT_STALENESS_MINUTES', 15)
# For games further out, update odds every hour (60 mins).
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
# Re-scan a league for new events every 6 hours to catch newly scheduled games.
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)

# --- OTHER OPERATIONAL SETTINGS ---
ODDS_POST_COMMENCEMENT_GRACE_HOURS = getattr(settings, 'THE_ODDS_API_POST_COMMENCEMENT_GRACE_HOURS', 1)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
DAYS_FROM_FOR_SCORES = getattr(settings, 'THE_ODDS_API_DAYS_FROM_SCORES', 3)


# --- Helper Function for Parsing Outcome Details ---
def parse_outcome_details(outcome_name_api, market_key_api):
    name_part, point_part = outcome_name_api, None
    if market_key_api in ['totals', 'h2h_spread', 'spreads']:
        try:
            parts = outcome_name_api.split()
            if len(parts) > 0 and parts[-1].replace('.', '', 1).lstrip('+-').isdigit():
                point_part = float(parts[-1])
                if len(parts) > 1: name_part = " ".join(parts[:-1])
                else: name_part = outcome_name_api
        except (ValueError, IndexError):
            logger.warning(f"Could not parse point from outcome: {outcome_name_api} for market {market_key_api}")
    return name_part, point_part

# --- Bet Settlement Task ---
@shared_task(bind=True, max_retries=3, default_retry_delay=10 * 60)
def settle_bets_for_fixture_task(self, fixture_id):
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, completed=True, home_team_score__isnull=False, away_team_score__isnull=False)
        logger.info(f"Settling bets for Fixture ID: {fixture_id}")
        home_score, away_score, outcomes_to_update = fixture.home_team_score, fixture.away_team_score, []
        for market in fixture.markets.all():
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'PENDING'
                if market.api_market_key == 'h2h':
                    if outcome.outcome_name == fixture.home_team_name: new_status = 'WON' if home_score > away_score else 'LOST'
                    elif outcome.outcome_name == fixture.away_team_name: new_status = 'WON' if away_score > home_score else 'LOST'
                    elif outcome.outcome_name.lower() == 'draw': new_status = 'WON' if home_score == away_score else 'LOST'
                elif market.api_market_key == 'totals':
                    if outcome.point_value is not None:
                        total_score = home_score + away_score
                        if 'over' in outcome.outcome_name.lower():
                            if total_score > outcome.point_value: new_status = 'WON'
                            elif total_score == outcome.point_value: new_status = 'PUSH'
                            else: new_status = 'LOST'
                        elif 'under' in outcome.outcome_name.lower():
                            if total_score < outcome.point_value: new_status = 'WON'
                            elif total_score == outcome.point_value: new_status = 'PUSH'
                            else: new_status = 'LOST'
                elif market.api_market_key in ['spreads', 'h2h_spread']:
                    if outcome.point_value is not None:
                        if outcome.outcome_name == fixture.home_team_name and (home_score + outcome.point_value) > away_score: new_status = 'WON'
                        elif outcome.outcome_name == fixture.home_team_name and (home_score + outcome.point_value) == away_score: new_status = 'PUSH'
                        elif outcome.outcome_name == fixture.home_team_name: new_status = 'LOST'
                        elif outcome.outcome_name == fixture.away_team_name and (away_score + outcome.point_value) > home_score: new_status = 'WON'
                        elif outcome.outcome_name == fixture.away_team_name and (away_score + outcome.point_value) == home_score: new_status = 'PUSH'
                        elif outcome.outcome_name == fixture.away_team_name: new_status = 'LOST'
                if new_status != 'PENDING': outcome.result_status = new_status; outcomes_to_update.append(outcome)
        if outcomes_to_update: MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status']); logger.info(f"Settled {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
    except FootballFixture.DoesNotExist: logger.warning(f"Fixture {fixture_id} not ready/found for settlement.")
    except Exception as e: logger.exception(f"Error settling bets for {fixture_id}: {e}"); raise self.retry(exc=e)

# --- Core Data Fetching Tasks ---
@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60)
def fetch_and_update_sports_leagues_task(self):
    client = TheOddsAPIClient(); logger.info("Starting league update task.")
    try:
        sports_data = client.get_sports(all_sports=True)
        if not sports_data: return "No sports data from API."
        created_count, updated_count = 0, 0
        for item in sports_data:
            key, title = item.get('key'), item.get('title')
            if not key or not title: continue
            _, created = League.objects.update_or_create(sport_key=key, defaults={'name': title, 'sport_title': title})
            if created: created_count += 1
            else: updated_count += 1
        logger.info(f"League update finished. C:{created_count}, U:{updated_count}.")
    except TheOddsAPIException as e:
        logger.error(f"API Error fetching leagues: {e}");
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None: raise self.retry(exc=e)
    except Exception as e: logger.exception("Unexpected error fetching leagues."); raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=10 * 60)
def fetch_events_for_league_task(self, league_id):
    try: league = League.objects.get(id=league_id, active=True)
    except League.DoesNotExist: return f"League {league_id} not found/active."
    client = TheOddsAPIClient(); logger.info(f"Fetching events for {league.sport_key}")
    try:
        events_data = client.get_events(sport_key=league.sport_key)
        if not events_data: league.last_fetched_events = timezone.now(); league.save(); return f"No events found for {league.sport_key}."
        created_count, updated_count = 0, 0
        for item in events_data:
            event_id, commence_str, home_team, away_team, sport_key = item.get('id'), item.get('commence_time'), item.get('home_team'), item.get('away_team'), item.get('sport_key')
            if not all([event_id, commence_str, home_team, away_team, sport_key]): continue
            try: commence_time = parser.isoparse(commence_str)
            except ValueError: continue
            with transaction.atomic():
                home_obj, away_obj = Team.get_or_create_team(home_team), Team.get_or_create_team(away_team)
                _, created = FootballFixture.objects.update_or_create(event_api_id=event_id, defaults={'league': league, 'sport_key': sport_key, 'commence_time': commence_time, 'home_team_name': home_team, 'away_team_name': away_team, 'home_team': home_obj, 'away_team': away_obj})
                if created: created_count += 1
                else: updated_count += 1
        league.last_fetched_events = timezone.now(); league.save()
        logger.info(f"Events task for {league.sport_key} finished. C:{created_count}, U:{updated_count}.")
    except TheOddsAPIException as e: logger.error(f"API Error fetching events for {league.sport_key}: {e}"); raise self.retry(exc=e)
    except Exception as e: logger.exception(f"Unexpected error fetching events for {league.sport_key}."); raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=5 * 60)
def fetch_odds_for_events_task(self, sport_key, event_ids_list, regions=None, markets=None):
    if not event_ids_list:
        logger.warning(f"fetch_odds_for_events_task called for {sport_key} with no event IDs. Task skipped.")
        return "No event IDs provided. Task skipped."
        
    current_regions = regions or DEFAULT_ODDS_API_REGIONS
    effective_markets = markets or DEFAULT_ODDS_API_MARKETS
    if sport_key.endswith("_winner"):
        logger.info(f"Adjusting markets to 'h2h' for outright sport: {sport_key}")
        effective_markets = "h2h"
        
    client = TheOddsAPIClient()
    logger.info(f"Fetching odds for {len(event_ids_list)} specific events in {sport_key}.")
    try:
        odds_data_list = client.get_odds(sport_key=sport_key, regions=current_regions, markets=effective_markets, event_ids=event_ids_list)
    except TheOddsAPIException as e:
        logger.error(f"API Error fetching odds for {sport_key}, IDs {event_ids_list}: {e}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None: raise self.retry(exc=e)
        return f"Failed for {sport_key} due to API error: {e}"
    except Exception as e:
        logger.exception(f"Unexpected error fetching odds for {sport_key}."); raise self.retry(exc=e)
        
    if not odds_data_list:
        FootballFixture.objects.filter(event_api_id__in=event_ids_list).update(last_odds_update=timezone.now())
        return "No odds data received from API for the given event IDs."

    processed_ids = set()
    for event_data in odds_data_list:
        event_id = event_data.get("id")
        if not event_id: continue
        processed_ids.add(event_id)
        try:
            fixture = FootballFixture.objects.get(event_api_id=event_id)
            with transaction.atomic():
                Market.objects.filter(fixture_display=fixture).delete()
                for bookmaker in event_data.get("bookmakers", []):
                    bookie, _ = Bookmaker.objects.update_or_create(api_bookmaker_key=bookmaker.get("key"), defaults={'name': bookmaker.get("title")})
                    for market_data in bookmaker.get("markets", []):
                        market_instance = Market.objects.create(fixture_display=fixture, bookmaker=bookie, api_market_key=market_data.get("key"), category=MarketCategory.objects.get_or_create(name=market_data.get("key").replace("_", " ").title())[0], last_updated_odds_api=parser.isoparse(market_data.get("last_update")))
                        for outcome in market_data.get("outcomes", []):
                            name, point = parse_outcome_details(outcome.get("name"), market_data.get("key"))
                            MarketOutcome.objects.create(market=market_instance, outcome_name=name, odds=float(outcome.get("price")), point_value=point)
            fixture.last_odds_update = timezone.now(); fixture.save()
            logger.info(f"Processed odds for event {event_id}")
        except FootballFixture.DoesNotExist: logger.warning(f"Fixture {event_id} from odds response not in DB. Might be from a different league.")
        except Exception as e: logger.exception(f"Error processing odds data for event {event_id}: {e}")
        
    unchecked_ids = set(event_ids_list) - processed_ids
    if unchecked_ids: FootballFixture.objects.filter(event_api_id__in=list(unchecked_ids)).update(last_odds_update=timezone.now())
    return f"Odds update complete for {len(processed_ids)} events."

@shared_task(bind=True, max_retries=2, default_retry_delay=15 * 60)
def fetch_scores_for_league_events_task(self, league_id):
    try: league = League.objects.get(id=league_id, active=True)
    except League.DoesNotExist: return f"League {league_id} not found/inactive."
    client = TheOddsAPIClient(); logger.info(f"Fetching scores for {league.sport_key}")
    try:
        now = timezone.now()
        commence_from = now - timedelta(days=DAYS_FROM_FOR_SCORES); commence_to = now + timedelta(minutes=30)
        fixtures_q = models.Q(league=league) & ((models.Q(completed=False, commence_time__gte=commence_from, commence_time__lte=commence_to)) | (models.Q(completed=True, updated_at__gte=now - timedelta(hours=6)))) & (models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lte=now - timedelta(minutes=30)))
        fixture_ids = list(FootballFixture.objects.filter(fixtures_q).values_list('event_api_id', flat=True).distinct()[:ODDS_FETCH_EVENT_BATCH_SIZE * 2])
        if not fixture_ids: return f"No fixtures for scores for {league.sport_key}."
        
        logger.info(f"Checking scores for {len(fixture_ids)} events in {league.sport_key}.")
        scores_data = client.get_scores(sport_key=league.sport_key, event_ids=fixture_ids)
        if not scores_data: FootballFixture.objects.filter(event_api_id__in=fixture_ids).update(last_score_update=timezone.now()); return f"No scores data from API for {league.sport_key}."
        
        updated_count, settlement_tasks, processed_ids = 0, 0, set()
        for score_item in scores_data:
            event_id = score_item.get('id')
            if not event_id: continue
            processed_ids.add(event_id)
            try:
                with transaction.atomic():
                    fixture = FootballFixture.objects.get(event_api_id=event_id)
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score.get('name') == score_item.get('home_team'): home_s = score.get('score')
                            elif score.get('name') == score_item.get('away_team'): away_s = score.get('score')
                    fixture.home_team_score = int(home_s) if home_s and home_s.isdigit() else None
                    fixture.away_team_score = int(away_s) if away_s and away_s.isdigit() else None
                    fixture.completed = score_item.get('completed', fixture.completed)
                    # Set status field based on completion and time
                    if fixture.completed:
                        fixture.status = 'COMPLETED'
                    elif fixture.commence_time <= timezone.now():
                        fixture.status = 'STARTED'
                    else:
                        fixture.status = 'PENDING'
                    fixture.last_score_update = timezone.now(); fixture.save()
                    updated_count += 1; logger.info(f"Updated scores for {event_id}: {fixture.home_team_score}-{fixture.away_team_score}, Comp:{fixture.completed}")
                    if fixture.completed and fixture.home_team_score is not None and MarketOutcome.objects.filter(market__fixture_display=fixture, result_status='PENDING').exists():
                        logger.info(f"Triggering settlement for {fixture.id}"); settle_bets_for_fixture_task.delay(fixture.id); settlement_tasks += 1
            except FootballFixture.DoesNotExist: logger.warning(f"Fixture {event_id} for score update not found.")
            except Exception as e: logger.exception(f"Error updating scores for {event_id}: {e}")
        
        unchecked_ids = set(fixture_ids) - processed_ids
        if unchecked_ids: FootballFixture.objects.filter(event_api_id__in=list(unchecked_ids)).update(last_score_update=now)
        logger.info(f"Score task for {league.sport_key}: Updated {updated_count}, Triggered {settlement_tasks} settlements.")
        return f"Scores for {league.sport_key}: Updated {updated_count}."
    except TheOddsAPIException as e:
        logger.error(f"API Error fetching scores for {league.sport_key}: {e}");
        if e.status_code in [429,500,502,503,504] or e.status_code is None: raise self.retry(exc=e)
    except Exception as e: logger.exception(f"Unexpected error fetching scores for {league.sport_key}."); raise self.retry(exc=e)

# --- Orchestrator Task ---
@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    logger.info("Orchestrator: run_the_odds_api_full_update_task started.")
    fetch_and_update_sports_leagues_task.apply_async()

    active_leagues = League.objects.filter(active=True)
    if not active_leagues.exists():
        logger.info("Orchestrator: No active leagues found. Ensure leagues are fetched and marked active in Admin.")
        return "No active leagues."

    now = timezone.now()
    event_discovery_staleness = now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)
    batch_size = ODDS_FETCH_EVENT_BATCH_SIZE

    for league in active_leagues:
        logger.info(f"Orchestrator: Processing league: {league.sport_key}")
        
        # Step 1: Discover events if the league's event list is stale.
        if league.last_fetched_events is None or league.last_fetched_events < event_discovery_staleness:
            logger.info(f"Orchestrator: Dispatching event discovery for {league.sport_key}.")
            fetch_events_for_league_task.apply_async(args=[league.id])
        
        # Step 2: Find fixtures that need their odds updated.
        imminent_max = now + timedelta(hours=2)
        imminent_stale = now - timedelta(minutes=ODDS_IMMINENT_STALENESS_MINUTES)
        upcoming_max = now + timedelta(days=ODDS_LEAD_TIME_DAYS)
        upcoming_stale = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)
        grace_min_time = now - timedelta(hours=ODDS_POST_COMMENCEMENT_GRACE_HOURS)

        fixtures_needing_q = models.Q(league=league, completed=False) & \
            ((models.Q(commence_time__gte=now, commence_time__lte=imminent_max) & (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_stale))) |
             (models.Q(commence_time__gt=imminent_max, commence_time__lte=upcoming_max) & (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=upcoming_stale))) |
             (models.Q(commence_time__gte=grace_min_time, commence_time__lt=now) & (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_stale))))
        
        event_ids = list(FootballFixture.objects.filter(fixtures_needing_q).values_list('event_api_id', flat=True).distinct())
        
        if event_ids:
            logger.info(f"Orchestrator: Found {len(event_ids)} existing events for odds update in {league.sport_key}.")
            for i in range(0, len(event_ids), batch_size):
                fetch_odds_for_events_task.apply_async(args=[league.sport_key, event_ids[i:i + batch_size]])
        else:
            # We no longer do a proactive fetch here to avoid 422 errors.
            logger.info(f"Orchestrator: No existing events match odds criteria for {league.sport_key}. No odds fetch dispatched.")

        # Step 3: Check for scores for this league
        fetch_scores_for_league_events_task.apply_async(args=[league.id])

    logger.info("Orchestrator: Finished dispatching sub-tasks.")
    return "Full data update process initiated for active leagues."
