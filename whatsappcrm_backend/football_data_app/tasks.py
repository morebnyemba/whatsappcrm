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

# --- Settings or Defaults ---
# Fetched from Django settings with hardcoded fallbacks if not defined there.
# Ensure these THE_ODDS_API_* variables are in your project's settings.py for configurability.
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 2)
ODDS_IMMINENT_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_IMMINENT_STALENESS_MINUTES', 15)
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
ODDS_POST_COMMENCEMENT_GRACE_HOURS = getattr(settings, 'THE_ODDS_API_POST_COMMENCEMENT_GRACE_HOURS', 1)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk")
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,spreads")


# --- Helper Function for Parsing Outcome Details ---
def parse_outcome_details(outcome_name_api, market_key_api):
    name_part = outcome_name_api
    point_part = None
    if market_key_api in ['totals', 'h2h_spread'] or 'spreads' in market_key_api:
        try:
            parts = outcome_name_api.split()
            if len(parts) > 0:
                potential_point_str = parts[-1]
                if potential_point_str.replace('.', '', 1).lstrip('+-').isdigit():
                    point_part = float(potential_point_str)
                    if len(parts) > 1:
                        name_part = " ".join(parts[:-1])
                    else:
                        name_part = outcome_name_api
        except ValueError:
            logger.warning(f"Could not parse point from outcome: {outcome_name_api} for market {market_key_api}")
            name_part = outcome_name_api
            point_part = None
    return name_part, point_part

# --- Bet Settlement Task ---
@shared_task(bind=True, max_retries=3, default_retry_delay=10 * 60)
def settle_bets_for_fixture_task(self, fixture_id):
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, completed=True, home_team_score__isnull=False, away_team_score__isnull=False)
        logger.info(f"Task started: settle_bets_for_fixture_task for Fixture ID: {fixture_id} ({fixture.home_team_name} vs {fixture.away_team_name})")

        home_score = fixture.home_team_score
        away_score = fixture.away_team_score
        outcomes_to_update = []

        for market in fixture.markets.all():
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'PENDING'
                if market.api_market_key == 'h2h':
                    if outcome.outcome_name == fixture.home_team_name:
                        if home_score > away_score: new_status = 'WON'
                        else: new_status = 'LOST'
                    elif outcome.outcome_name == fixture.away_team_name:
                        if away_score > home_score: new_status = 'WON'
                        else: new_status = 'LOST'
                    elif outcome.outcome_name.lower() == 'draw':
                        if home_score == away_score: new_status = 'WON'
                        else: new_status = 'LOST'
                elif market.api_market_key == 'totals':
                    total_score = home_score + away_score
                    if outcome.point_value is not None:
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
                        if outcome.outcome_name == fixture.home_team_name:
                            if (home_score + outcome.point_value) > away_score: new_status = 'WON'
                            elif (home_score + outcome.point_value) == away_score: new_status = 'PUSH'
                            else: new_status = 'LOST'
                        elif outcome.outcome_name == fixture.away_team_name:
                            if (away_score + outcome.point_value) > home_score: new_status = 'WON'
                            elif (away_score + outcome.point_value) == home_score: new_status = 'PUSH'
                            else: new_status = 'LOST'
                
                if new_status != 'PENDING' and new_status != outcome.result_status :
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)

        if outcomes_to_update:
            with transaction.atomic():
                MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
            logger.info(f"Settled {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
        else:
            logger.info(f"No pending outcomes found or no status changes for fixture {fixture_id}.")
        return f"Bet settlement attempt complete for fixture {fixture_id}. Updated: {len(outcomes_to_update)}."
    except FootballFixture.DoesNotExist:
        logger.warning(f"Fixture ID {fixture_id} not found or not ready for settlement. Skipping.")
        return f"Fixture {fixture_id} not ready/found."
    except Exception as e:
        logger.exception(f"Unexpected error in settle_bets_for_fixture_task for fixture ID {fixture_id}: {e}")
        raise self.retry(exc=e)

# --- Core Data Fetching Tasks ---
@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60)
def fetch_and_update_sports_leagues_task(self):
    client = TheOddsAPIClient()
    try:
        logger.info("Task started: fetch_and_update_sports_leagues_task")
        sports_data = client.get_sports(all_sports=True)
        if not sports_data:
            logger.warning("No sports data received from API for leagues.")
            return "No sports data received."
        updated_count, created_count = 0, 0
        for sport_item in sports_data:
            sport_key, sport_title, active_api = sport_item.get('key'), sport_item.get('title'), sport_item.get('active', True)
            if not sport_key or not sport_title: logger.warning(f"Skipping sport item: {sport_item}"); continue
            with transaction.atomic():
                league, created = League.objects.update_or_create(sport_key=sport_key, defaults={'name': sport_title, 'sport_title': sport_title})
                if created: created_count += 1; logger.info(f"Created League: {league.sport_key} - {league.name}")
                else: updated_count += 1
        logger.info(f"Task finished: fetch_and_update_sports_leagues_task. C:{created_count}, U:{updated_count}.")
        return f"Sports/Leagues update complete. C:{created_count}, U:{updated_count}."
    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_and_update_sports_leagues_task: {e.status_code} - {str(e)}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None: raise self.retry(exc=e)
        return f"Failed due to API error: {str(e)}"
    except Exception as e: logger.exception("Unexpected error in fetch_and_update_sports_leagues_task."); raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=10 * 60)
def fetch_events_for_league_task(self, league_id):
    try: league = League.objects.get(id=league_id, active=True)
    except League.DoesNotExist: logger.warning(f"League {league_id} not found/active."); return f"League {league_id} not found/inactive."
    client = TheOddsAPIClient()
    try:
        logger.info(f"Task started: fetch_events_for_league_task for League: {league.sport_key}")
        events_data = client.get_events(sport_key=league.sport_key)
        if not events_data:
            logger.info(f"No events data from /events for {league.sport_key}."); league.last_fetched_events = timezone.now(); league.save()
            return f"No events data for {league.sport_key} via /events."
        created_count, updated_count = 0, 0
        for event_item in events_data:
            event_api_id=event_item.get('id'); commence_time_str=event_item.get('commence_time'); home_team_name=event_item.get('home_team'); away_team_name=event_item.get('away_team'); sport_key_api=event_item.get('sport_key')
            if not all([event_api_id, commence_time_str, home_team_name, away_team_name, sport_key_api]): logger.warning(f"Skip /events item {event_item}"); continue
            try: commence_time = parser.isoparse(commence_time_str)
            except ValueError: logger.error(f"Parse commence_time fail: {commence_time_str} for event {event_api_id}. Skip."); continue
            with transaction.atomic():
                home_team_obj = Team.get_or_create_team(home_team_name); away_team_obj = Team.get_or_create_team(away_team_name)
                fixture, created = FootballFixture.objects.update_or_create(event_api_id=event_api_id, defaults={'league': league, 'sport_key': sport_key_api, 'commence_time': commence_time, 'home_team_name': home_team_name, 'away_team_name': away_team_name, 'home_team': home_team_obj, 'away_team': away_team_obj})
                if created: created_count += 1; logger.info(f"Created Fixture (via /events): {fixture.event_api_id} for {league.sport_key}")
                else: updated_count += 1
        league.last_fetched_events = timezone.now(); league.save()
        logger.info(f"Task finished: fetch_events_for_league_task for {league.sport_key}. C:{created_count}, U:{updated_count}.")
        return f"Events from /events complete for {league.sport_key}."
    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_events_for_league_task for {league.sport_key}: {e.status_code} - {str(e)}")
        if e.status_code in [429, 500, 502, 503, 504] or e.status_code is None: raise self.retry(exc=e)
        return f"Failed for {league.sport_key} due to API error: {str(e)}"
    except Exception as e: logger.exception(f"Unexpected error in fetch_events_for_league_task for {league.sport_key}."); raise self.retry(exc=e)

@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60)
def fetch_odds_for_events_task(self, sport_key, event_ids_list, regions=None, markets=None):
    current_regions = regions or DEFAULT_ODDS_API_REGIONS
    default_markets_str = markets or DEFAULT_ODDS_API_MARKETS
    client = TheOddsAPIClient()
    odds_data_list = []
    commence_time_from_iso, commence_time_to_iso = None, None
    is_proactive_fetch = not bool(event_ids_list)
    
    # Adjust markets for outrights
    effective_markets = default_markets_str
    if sport_key.endswith("_winner"):
        logger.info(f"Adjusting markets for outright sport: {sport_key}")
        effective_markets = "h2h"  # 'h2h' is often used for outrights, or check API for 'outrights' key

    if is_proactive_fetch:
        logger.info(f"Proactive odds fetch for sport {sport_key}.")
        if not sport_key.endswith("_winner"):
            now = timezone.now()
            commence_time_from_iso = now.isoformat()
            commence_time_to_iso = (now + timedelta(days=ODDS_LEAD_TIME_DAYS)).isoformat()
    
    try:
        odds_data_list = client.get_odds(
            sport_key=sport_key, regions=current_regions, markets=effective_markets,
            event_ids=event_ids_list if event_ids_list else None,
            commence_time_from=commence_time_from_iso, 
            commence_time_to=commence_time_to_iso
        )
    except TheOddsAPIException as e:
        log_msg_detail = f"IDs: {event_ids_list if event_ids_list else 'proactive'}"
        logger.error(f"API Error in fetch_odds_for_events_task for {sport_key} ({log_msg_detail}): {e.status_code} - {str(e)}")
        if e.status_code in [429, 500, 502, 503, 504] or (e.status_code == 422 and e.response_text and "Rate limit" in e.response_text) or e.status_code is None:
            raise self.retry(exc=e)
        if event_ids_list: FootballFixture.objects.filter(event_api_id__in=event_ids_list).update(last_odds_update=timezone.now())
        return f"Failed for {sport_key} ({log_msg_detail}) due to API error: {str(e)}"
    except Exception as e:
        logger.exception(f"Unexpected error in fetch_odds_for_events_task for sport {sport_key} ({log_msg_detail}).")
        raise self.retry(exc=e)
        
    if not odds_data_list:
        if event_ids_list: FootballFixture.objects.filter(event_api_id__in=event_ids_list).update(last_odds_update=timezone.now())
        return "No odds data received from API."

    processed_event_ids = set()
    for event_data in odds_data_list:
        event_api_id = event_data.get("id")
        if not event_api_id: continue
        processed_event_ids.add(event_api_id)
        try:
            home_team_name, away_team_name = event_data.get("home_team"), event_data.get("away_team")
            commence_time = parser.isoparse(event_data.get("commence_time"))
            event_sport_key = event_data.get("sport_key")
            league_obj, _ = League.objects.get_or_create(sport_key=event_sport_key, defaults={'name': event_data.get('sport_title', event_sport_key.replace("_", " ").title())})
            home_team_obj, away_team_obj = Team.get_or_create_team(home_team_name), Team.get_or_create_team(away_team_name)
            
            fixture, created = FootballFixture.objects.update_or_create(
                event_api_id=event_api_id,
                defaults={ 'league': league_obj, 'sport_key': event_sport_key, 'commence_time': commence_time, 'home_team_name': home_team_name, 'away_team_name': away_team_name, 'home_team': home_team_obj, 'away_team': away_team_obj }
            )
            if created: logger.info(f"Fixture {event_api_id} created processing odds.")

            with transaction.atomic():
                Market.objects.filter(fixture_display=fixture).delete()
                for bookmaker_data in event_data.get("bookmakers", []):
                    bookie, _ = Bookmaker.objects.update_or_create(api_bookmaker_key=bookmaker_data.get("key"), defaults={'name': bookmaker_data.get("title")})
                    for market_data in bookmaker_data.get("markets", []):
                        market_instance = Market.objects.create(fixture_display=fixture, bookmaker=bookie, api_market_key=market_data.get("key"), category=MarketCategory.objects.get_or_create(name=market_data.get("key").replace("_", " ").title())[0], last_updated_odds_api=parser.isoparse(market_data.get("last_update")))
                        for outcome_data in market_data.get("outcomes", []):
                            parsed_name, parsed_point = parse_outcome_details(outcome_data.get("name"), market_data.get("key"))
                            MarketOutcome.objects.create(market=market_instance, outcome_name=parsed_name, odds=float(outcome_data.get("price")), point_value=parsed_point)
            fixture.last_odds_update = timezone.now(); fixture.save()
            logger.info(f"Processed odds for event {event_api_id}")
        except Exception as e: logger.exception(f"Error processing odds data for event {event_api_id}: {e}")

    if event_ids_list:
        unprocessed_ids = set(event_ids_list) - processed_event_ids
        if unprocessed_ids: FootballFixture.objects.filter(event_api_id__in=list(unprocessed_ids)).update(last_odds_update=timezone.now()); logger.info(f"Marked {len(unprocessed_ids)} events as checked (no data).")
    return f"Odds update complete for {len(processed_event_ids)} events."

@shared_task(bind=True, max_retries=2, default_retry_delay=15 * 60)
def fetch_scores_for_league_events_task(self, league_id):
    try: league = League.objects.get(id=league_id, active=True)
    except League.DoesNotExist: logger.warning(f"League {league_id} not found/inactive."); return f"League {league_id} not found/inactive."
    client = TheOddsAPIClient()
    try:
        logger.info(f"Task started: fetch_scores_for_league_events_task for {league.sport_key}")
        now = timezone.now()
        days_from = getattr(settings, 'THE_ODDS_API_DAYS_FROM_SCORES', 3)
        batch_size = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
        commence_from = now - timedelta(days=days_from); commence_to = now + timedelta(minutes=30)
        
        fixtures_q = models.Q(league=league) & ((models.Q(completed=False, commence_time__gte=commence_from, commence_time__lte=commence_to)) | (models.Q(completed=True, updated_at__gte=now - timedelta(hours=6)))) & (models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lte=now - timedelta(minutes=30)))
        fixture_ids = list(FootballFixture.objects.filter(fixtures_q).values_list('event_api_id', flat=True).distinct()[:batch_size * 2])
        if not fixture_ids: logger.info(f"No fixtures for score update for {league.sport_key}."); return f"No fixtures for scores for {league.sport_key}."
        
        logger.info(f"Checking scores for {len(fixture_ids)} events in {league.sport_key}.")
        scores_data = client.get_scores(sport_key=league.sport_key, event_ids=fixture_ids)
        if not scores_data:
            logger.info(f"No scores data from API for {league.sport_key}, events: {fixture_ids}.")
            FootballFixture.objects.filter(event_api_id__in=fixture_ids).update(last_score_update=timezone.now())
            return f"No scores data from API for {league.sport_key}."
        
        updated_count, settlement_tasks, processed_ids = 0, 0, set()
        for score_item in scores_data:
            event_api_id = score_item.get('id')
            if not event_api_id: continue
            processed_ids.add(event_api_id)
            try:
                with transaction.atomic():
                    fixture = FootballFixture.objects.get(event_api_id=event_api_id)
                    home_s, away_s = None, None; home_team_name, away_team_name = score_item.get('home_team'), score_item.get('away_team')
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score.get('name') == home_team_name: home_s = score.get('score')
                            elif score.get('name') == away_team_name: away_s = score.get('score')
                    
                    fixture.home_team_score = int(home_s) if home_s and home_s.isdigit() else None
                    fixture.away_team_score = int(away_s) if away_s and away_s.isdigit() else None
                    fixture.completed = score_item.get('completed', fixture.completed)
                    fixture.last_score_update = now
                    fixture.save()
                    updated_count += 1
                    logger.info(f"Updated scores for {event_api_id}: {fixture.home_team_score}-{fixture.away_team_score}, Comp:{fixture.completed}")

                    if fixture.completed and fixture.home_team_score is not None and MarketOutcome.objects.filter(market__fixture_display=fixture, result_status='PENDING').exists():
                        logger.info(f"Triggering settlement for {fixture.id}"); settle_bets_for_fixture_task.delay(fixture.id); settlement_tasks += 1
            except FootballFixture.DoesNotExist: logger.warning(f"Fixture {event_api_id} for score update not found.")
            except Exception as e: logger.exception(f"Error updating scores for {event_api_id}: {e}")
        
        unchecked_ids = set(fixture_ids) - processed_ids
        if unchecked_ids: FootballFixture.objects.filter(event_api_id__in=list(unchecked_ids)).update(last_score_update=now)
        logger.info(f"Score task for {league.sport_key}: Updated {updated_count}, Triggered {settlement_tasks} settlements.")
        return f"Scores for {league.sport_key}: Updated {updated_count}."
    except TheOddsAPIException as e:
        logger.error(f"API Error in fetch_scores for {league.sport_key}: {e.status_code} - {str(e)}");
        if e.status_code in [429,500,502,503,504] or e.status_code is None: raise self.retry(exc=e)
        return f"API error scores {league.sport_key}: {str(e)}"
    except Exception as e: logger.exception(f"Unexpected error scores for {league.sport_key}."); raise self.retry(exc=e)

# --- Orchestrator Task ---
@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    logger.info("Orchestrator: run_the_odds_api_full_update_task started.")
    fetch_and_update_sports_leagues_task.apply_async()

    active_leagues = League.objects.filter(active=True)
    if not active_leagues.exists(): logger.info("Orchestrator: No active leagues."); return "No active leagues."

    now = timezone.now()
    event_discovery_staleness = now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)
    batch_size = ODDS_FETCH_EVENT_BATCH_SIZE

    for league in active_leagues:
        logger.info(f"Orchestrator: Processing league: {league.sport_key} ({league.name})")
        if league.last_fetched_events is None or league.last_fetched_events < event_discovery_staleness:
            logger.info(f"Orchestrator: {league.sport_key} needs event discovery. Dispatching fetch_events_for_league_task.")
            fetch_events_for_league_task.apply_async(args=[league.id])
        else:
            logger.info(f"Orchestrator: {league.sport_key} event discovery recent. Skip explicit /events fetch.")

        imminent_max = now + timedelta(hours=2); imminent_stale = now - timedelta(minutes=ODDS_IMMINENT_STALENESS_MINUTES)
        upcoming_max = now + timedelta(days=ODDS_LEAD_TIME_DAYS); upcoming_stale = now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES)
        grace_min_time = now - timedelta(hours=ODDS_POST_COMMENCEMENT_GRACE_HOURS)

        fixtures_needing_q = models.Q(league=league, completed=False) & \
            ((models.Q(commence_time__gte=now, commence_time__lte=imminent_max) & (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_stale))) |
             (models.Q(commence_time__gt=imminent_max, commence_time__lte=upcoming_max) & (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=upcoming_stale))) |
             (models.Q(commence_time__gte=grace_min_time, commence_time__lt=now) & (models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lte=imminent_stale))))
        
        event_ids = list(FootballFixture.objects.filter(fixtures_needing_q).values_list('event_api_id', flat=True).distinct()[:batch_size * 5])
        
        if event_ids:
            logger.info(f"Orchestrator: Found {len(event_ids)} existing events in {league.sport_key} for odds update.")
            for i in range(0, len(event_ids), batch_size):
                fetch_odds_for_events_task.apply_async(args=[league.sport_key, event_ids[i:i + batch_size]])
        else:
            logger.info(f"Orchestrator: No existing events match odds criteria for {league.sport_key}. Proactive odds fetch.")
            fetch_odds_for_events_task.apply_async(args=[league.sport_key, []])

        fetch_scores_for_league_events_task.apply_async(args=[league.id])

    logger.info("Orchestrator: Finished dispatching sub-tasks for active leagues.")
    return "Full data update process initiated for active leagues."
