# football_data_app/tasks.py
import logging
from django.conf import settings
from celery import shared_task, chain
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta
from decimal import Decimal

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# --- Configuration ---
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us")
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,spreads,btts")
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)

# --- Helper Function ---
def _parse_outcome_details(outcome_name_api, market_key_api):
    name_part, point_part = outcome_name_api, None
    if market_key_api in ['totals', 'spreads']:
        try:
            parts = outcome_name_api.split()
            last_part = parts[-1]
            if last_part.replace('.', '', 1).lstrip('+-').isdigit():
                point_part = float(last_part)
                name_part = " ".join(parts[:-1]) or outcome_name_api
        except (ValueError, IndexError):
            logger.debug(f"Could not parse point from outcome: '{outcome_name_api}' for market '{market_key_api}' - often expected for non-numeric outcomes.")
    return name_part, point_part

# --- Data Fetching & Processing Tasks ---

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """Step 1: Fetches and updates football leagues from the API."""
    task_id = self.request.id
    logger.info(f"Task {task_id}: Pipeline Step 1: Starting league fetch task.")
    client = TheOddsAPIClient()
    created_count, updated_count = 0, 0
    try:
        logger.debug(f"Task {task_id}: Calling TheOddsAPIClient.get_sports(all_sports=True).")
        sports_data = client.get_sports(all_sports=True)
        logger.info(f"Task {task_id}: Received {len(sports_data)} sports from API.")

        for item in sports_data:
            if 'soccer' not in item.get('key', ''):
                logger.debug(f"Task {task_id}: Skipping non-soccer sport: {item.get('key')}")
                continue
            
            league_api_id = item['key']
            league_name = item.get('title', 'Unknown League')
            _, created = League.objects.update_or_create(
                api_id=league_api_id,
                defaults={'name': league_name, 'sport_key': 'soccer', 'active': True, 'logo_url': item.get('logo')}
            )
            if created:
                created_count += 1
                logger.debug(f"Task {task_id}: Created new league: {league_name} ({league_api_id}).")
            else:
                updated_count += 1
                logger.debug(f"Task {task_id}: Updated existing league: {league_name} ({league_api_id}).")

        logger.info(f"Task {task_id}: Leagues Task Complete: {created_count} created, {updated_count} updated.")
        return f"Processed {created_count + updated_count} leagues."
    except Exception as e:
        logger.exception(f"Task {task_id}: Critical error in league fetching task. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id):
    """(Sub-task) Fetches events for a specific league."""
    task_id = self.request.id
    logger.info(f"Task {task_id}: Starting event fetch for league ID: {league_id}.")
    client, created_count, updated_count = TheOddsAPIClient(), 0, 0
    try:
        league = League.objects.get(id=league_id)
        logger.info(f"Task {task_id}: Fetching events for league: {league.name} (API ID: {league.api_id}).")
        events_data = client.get_events(sport_key=league.api_id)
        logger.info(f"Task {task_id}: Received {len(events_data)} events from API for {league.name}.")
        
        for item in events_data:
            event_api_id = item.get('id')
            home_team_name = item.get('home_team')
            away_team_name = item.get('away_team')

            if not home_team_name or not away_team_name:
                logger.warning(f"Task {task_id}: Skipping event ID {event_api_id} as it lacks team data. Home: '{home_team_name}', Away: '{away_team_name}'.")
                continue

            with transaction.atomic():
                home_obj, home_created = Team.objects.get_or_create(name=home_team_name)
                away_obj, away_created = Team.objects.get_or_create(name=away_team_name)
                if home_created: logger.debug(f"Task {task_id}: Created new home team: {home_team_name}.")
                if away_created: logger.debug(f"Task {task_id}: Created new away team: {away_team_name}.")
                
                fixture_match_date = parser.isoparse(item['commence_time'])
                fixture_obj, created = FootballFixture.objects.update_or_create(
                    api_id=event_api_id,
                    defaults={
                        'league': league, 'home_team': home_obj, 'away_team': away_obj,
                        'match_date': fixture_match_date,
                        'status': 'SCHEDULED'
                    }
                )
                if created:
                    created_count += 1
                    logger.debug(f"Task {task_id}: Created new fixture: {home_team_name} vs {away_team_name} (ID: {fixture_obj.id}, API ID: {event_api_id}).")
                else:
                    updated_count += 1
                    logger.debug(f"Task {task_id}: Updated existing fixture: {home_team_name} vs {away_team_name} (ID: {fixture_obj.id}, API ID: {event_api_id}).")
            
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Task {task_id}: Events for {league.name} processed: {created_count} created, {updated_count} updated. League 'last_fetched_events' updated.")
    except League.DoesNotExist:
        logger.warning(f"Task {task_id}: League with ID {league_id} not found for event fetching. Skipping.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching events for league {league_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def process_leagues_and_dispatch_subtasks_task(self, previous_task_result=None):
    """
    Step 2 of the main pipeline. Iterates through leagues to dispatch odds and score updates.
    """
    task_id = self.request.id
    now = timezone.now()
    logger.info(f"Task {task_id}: Pipeline Step 2: Processing leagues and dispatching sub-tasks.")
    
    leagues = League.objects.filter(active=True)
    if not leagues.exists():
        logger.warning(f"Task {task_id}: Orchestrator: No active leagues found to process. Exiting.")
        return

    logger.info(f"Task {task_id}: Found {leagues.count()} active leagues to process.")
    for league in leagues:
        logger.debug(f"Task {task_id}: Processing league: {league.name} (ID: {league.id}, API ID: {league.api_id}).")

        # Dispatch event fetching if stale
        if not league.last_fetched_events or league.last_fetched_events < (now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)):
            logger.info(f"Task {task_id}: League {league.name} event discovery is stale. Dispatching fetch_events_for_league_task.")
            fetch_events_for_league_task.apply_async(args=[league.id])
        else:
            logger.debug(f"Task {task_id}: League {league.name} event discovery is up-to-date (last fetched: {league.last_fetched_events}).")

        # Query for fixtures that need odds updates
        stale_odds_fixtures = FootballFixture.objects.filter(
            league=league,
            status=FootballFixture.FixtureStatus.SCHEDULED,
            match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
        ).filter(
            models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES))
        )
        event_ids_for_odds = list(stale_odds_fixtures.values_list('api_id', flat=True))
        
        if event_ids_for_odds:
            logger.info(f"Task {task_id}: Found {len(event_ids_for_odds)} fixtures needing odds update for league: {league.name}.")
            for i in range(0, len(event_ids_for_odds), ODDS_FETCH_EVENT_BATCH_SIZE):
                batch = event_ids_for_odds[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
                logger.debug(f"Task {task_id}: Dispatching odds fetch batch for {len(batch)} events in {league.name}. Batch IDs: {batch}.")
                fetch_odds_for_event_batch_task.apply_async(args=[league.api_id, batch])
        else:
            logger.info(f"Task {task_id}: No fixtures needing odds update for league: {league.name}.")

        # Dispatch score fetching for the league
        logger.debug(f"Task {task_id}: Dispatching fetch_scores_for_league_task for league: {league.name}.")
        fetch_scores_for_league_task.apply_async(args=[league.id])
        
    logger.info(f"Task {task_id}: Orchestrator: Finished dispatching jobs for {leagues.count()} leagues.")

# --- Main Orchestrator ---
@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    """Main orchestrator task that uses a Celery chain for a reliable data pipeline."""
    logger.info("Orchestrator: Kicking off the full data update pipeline.")
    
    pipeline = chain(
        fetch_and_update_leagues_task.s(),
        process_leagues_and_dispatch_subtasks_task.s()
    )
    pipeline.apply_async()
    
    logger.info("Orchestrator: Update pipeline has been dispatched.")
    return "Full data update pipeline initiated successfully."

# --- Individual Sub-Tasks ---

@shared_task(bind=True, max_retries=1, default_retry_delay=60) # Less retries for single event, faster feedback
def fetch_odds_for_single_event_task(self, sport_key, event_id, markets=None, regions=None):
    """
    (Sub-task) Fetches and updates odds for a single event.
    Used as a fallback when batch fetching encounters Unprocessable Entity errors.
    """
    task_id = self.request.id
    markets_to_fetch = markets or DEFAULT_ODDS_API_MARKETS
    regions_to_fetch = regions or DEFAULT_ODDS_API_REGIONS
    client = TheOddsAPIClient()

    logger.info(f"Task {task_id}: Attempting to fetch odds for single event {event_id} in {sport_key} for markets: '{markets_to_fetch}'.")

    try:
        odds_data = client.get_odds(
            sport_key=sport_key,
            event_ids=[event_id],
            regions=regions_to_fetch,
            markets=markets_to_fetch
        )

        if not odds_data:
            logger.warning(f"Task {task_id}: No odds data returned for single event ID {event_id}. It might be too old or not yet available from API.")
            return

        event_data = odds_data[0] # Expecting only one item in the list
        
        fixture = FootballFixture.objects.filter(api_id=event_data['id']).first()
        if not fixture:
            logger.warning(f"Task {task_id}: Fixture with API ID {event_data['id']} not found in DB for single event processing, skipping.")
            return

        with transaction.atomic():
            logger.debug(f"Task {task_id}: Starting atomic transaction for fixture {fixture.id} ({fixture.api_id}).")
            Market.objects.filter(fixture_display=fixture).delete()
            logger.debug(f"Task {task_id}: Cleared existing markets for fixture {fixture.id}.")
            
            for bookmaker_data in event_data.get('bookmakers', []):
                bookmaker_key = bookmaker_data['key']
                bookmaker_title = bookmaker_data['title']
                bookmaker, book_created = Bookmaker.objects.get_or_create(api_bookmaker_key=bookmaker_key, defaults={'name': bookmaker_title})
                if book_created: logger.debug(f"Task {task_id}: Created new bookmaker: {bookmaker.name} ({bookmaker.api_bookmaker_key}).")
                
                for market_data in bookmaker_data.get('markets', []):
                    market_key = market_data['key']
                    market_category_name = market_key.replace("_", " ").title()
                    category, cat_created = MarketCategory.objects.get_or_create(name=market_category_name)
                    if cat_created: logger.debug(f"Task {task_id}: Created new market category: {category.name}.")

                    market_instance = Market.objects.create(
                        fixture_display=fixture, bookmaker=bookmaker, category=category,
                        api_market_key=market_key, last_updated_odds_api=parser.isoparse(market_data['last_update'])
                    )
                    logger.debug(f"Task {task_id}: Created market {market_key} for bookmaker {bookmaker_key} on fixture {fixture.id}.")
                    
                    for outcome_data in market_data.get('outcomes', []):
                        outcome_name_api = outcome_data['name']
                        outcome_price = outcome_data['price']
                        name, point = _parse_outcome_details(outcome_name_api, market_key)
                        MarketOutcome.objects.create(market=market_instance, outcome_name=name, odds=outcome_price, point_value=point)
                        logger.debug(f"Task {task_id}: Created outcome '{name}' ({outcome_price}) for market {market_key}.")
            
            fixture.last_odds_update = timezone.now()
            fixture.save(update_fields=['last_odds_update'])
            logger.info(f"Task {task_id}: Successfully processed and updated odds for single fixture: {fixture.id} ({fixture.api_id}).")

    except TheOddsAPIException as e:
        # Specific handling for 422: don't retry, it's likely a persistent issue for this event ID.
        if e.status_code == 422:
            logger.warning(
                f"Task {task_id}: 422 Unprocessable Entity for single event {event_id} in {sport_key}. "
                f"This event ID is likely invalid or too old for odds (Response: '{e.response_text or e.response_json}'). "
                "Will NOT retry this single event."
            )
            return None # Do not retry
        else:
            logger.error(f"Task {task_id}: API Error fetching odds for single event {event_id} in {sport_key}: {e} (Status: {e.status_code}, Response: '{e.response_text or e.response_json}'). Retrying...")
            raise self.retry(exc=e) # Retry other types of errors
    except FootballFixture.DoesNotExist:
        logger.warning(f"Task {task_id}: Fixture with API ID {event_id} not found for single event processing, skipping. Could be removed from source.")
        return None
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching odds for single event {event_id} in {sport_key}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, sport_key, event_ids, markets=None, regions=None):
    """
    (Sub-task) Fetches and updates odds for a batch of events.
    If a 422 Unprocessable Entity error occurs for the batch, it dispatches
    individual tasks for each event ID in the batch.
    """
    task_id = self.request.id
    markets_to_fetch = markets or DEFAULT_ODDS_API_MARKETS
    regions_to_fetch = regions or DEFAULT_ODDS_API_REGIONS
    client = TheOddsAPIClient()

    logger.info(f"Task {task_id}: Attempting to fetch odds for {len(event_ids)} events in {sport_key} for markets: '{markets_to_fetch}' (Batch attempt).")
    logger.debug(f"Task {task_id}: Batch Event IDs: {event_ids}")
    
    try:
        odds_data = client.get_odds(
            sport_key=sport_key, 
            event_ids=event_ids, 
            regions=regions_to_fetch, 
            markets=markets_to_fetch
        )
        
        if not odds_data:
            logger.info(f"Task {task_id}: No odds data returned for batch of {len(event_ids)} events in {sport_key}. All events might be too old or not yet available.")
            return

        fixtures_map = {item.api_id: item for item in FootballFixture.objects.filter(api_id__in=event_ids)}
        successful_processed_count = 0
        
        with transaction.atomic():
            logger.debug(f"Task {task_id}: Starting atomic transaction for batch odds processing.")
            for event_data in odds_data:
                fixture_api_id = event_data['id']
                fixture = fixtures_map.get(fixture_api_id)
                if not fixture:
                    logger.warning(f"Task {task_id}: Fixture with API ID {fixture_api_id} not found in DB for batch processing. Skipping odds for this event.")
                    continue
                
                Market.objects.filter(fixture_display=fixture).delete()
                logger.debug(f"Task {task_id}: Cleared existing markets for fixture {fixture.id} ({fixture_api_id}).")
                
                for bookmaker_data in event_data.get('bookmakers', []):
                    bookmaker_key = bookmaker_data['key']
                    bookmaker, _ = Bookmaker.objects.get_or_create(api_bookmaker_key=bookmaker_key, defaults={'name': bookmaker_data['title']})
                    
                    for market_data in bookmaker_data.get('markets', []):
                        market_key = market_data['key']
                        category, _ = MarketCategory.objects.get_or_create(name=market_key.replace("_", " ").title())
                        
                        market_instance = Market.objects.create(
                            fixture_display=fixture, bookmaker=bookmaker, category=category,
                            api_market_key=market_key, last_updated_odds_api=parser.isoparse(market_data['last_update'])
                        )
                        logger.debug(f"Task {task_id}: Created market {market_key} for bookmaker {bookmaker_key} on fixture {fixture_api_id}.")
                        
                        for outcome_data in market_data.get('outcomes', []):
                            name, point = _parse_outcome_details(outcome_data['name'], market_key)
                            MarketOutcome.objects.create(market=market_instance, outcome_name=name, odds=outcome_data['price'], point_value=point)
                            logger.debug(f"Task {task_id}: Created outcome '{name}' for market {market_key} on fixture {fixture_api_id}.")
                
                fixture.last_odds_update = timezone.now()
                fixture.save(update_fields=['last_odds_update'])
                successful_processed_count += 1
                logger.debug(f"Task {task_id}: Updated last_odds_update for fixture {fixture.id} ({fixture_api_id}).")
        
        logger.info(f"Task {task_id}: Successfully processed odds for {successful_processed_count} fixtures from the batch for {sport_key}.")

    except TheOddsAPIException as e:
        if e.status_code == 422:
            logger.warning(
                f"Task {task_id}: Batch odds fetch for {sport_key} received 422 Unprocessable Entity. "
                f"Likely some event IDs are invalid. Delegating to single-event tasks. "
                f"Problematic batch event IDs: {event_ids}. "
                f"API Error: {e.response_text or e.response_json}."
            )
            for event_id in event_ids:
                logger.debug(f"Task {task_id}: Dispatching fetch_odds_for_single_event_task for event ID: {event_id}.")
                fetch_odds_for_single_event_task.apply_async(
                    args=[sport_key, event_id, markets_to_fetch, regions_to_fetch]
                )
            return f"Batch failed, dispatched {len(event_ids)} individual tasks."
        else:
            logger.error(f"Task {task_id}: API Error fetching odds for {sport_key} (Batch Event IDs: {event_ids}): {e} (Status: {e.status_code}, Response: '{e.response_text or e.response_json}'). Retrying batch...")
            raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching odds for {sport_key} (Batch Event IDs: {event_ids}). Retrying batch...")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id):
    """(Sub-task) Fetches scores and updates status for a single league."""
    task_id = self.request.id
    now = timezone.now()
    logger.info(f"Task {task_id}: Starting score fetch for league ID: {league_id}.")
    try:
        league = League.objects.get(id=league_id)
        
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status=FootballFixture.FixtureStatus.LIVE) |
            models.Q(league=league, status=FootballFixture.FixtureStatus.SCHEDULED, match_date__lt=now + timedelta(minutes=5)),
            models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lt=now - timedelta(minutes=10))
        ).distinct()

        if not fixtures_to_check.exists():
            logger.info(f"Task {task_id}: No fixtures needing score update for league: {league.name}. Exiting.")
            return
            
        fixture_ids = list(fixtures_to_check.values_list('api_id', flat=True))
        logger.info(f"Task {task_id}: Found {len(fixture_ids)} fixtures needing score update for league: {league.name} (API ID: {league.api_id}).")
        logger.debug(f"Task {task_id}: Fixture IDs for score fetch: {fixture_ids}.")

        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=fixture_ids)
        logger.info(f"Task {task_id}: Received {len(scores_data)} scores from API for league {league.name}.")
        
        fixtures_map = {f.api_id: f for f in fixtures_to_check}

        for score_item in scores_data:
            fixture_api_id = score_item['id']
            fixture = fixtures_map.get(fixture_api_id)
            if not fixture:
                logger.warning(f"Task {task_id}: Score received for unknown fixture API ID {fixture_api_id}, skipping. Fixture not in local DB or not targeted.")
                continue

            with transaction.atomic():
                logger.debug(f"Task {task_id}: Processing score for fixture {fixture.id} ({fixture_api_id}).")
                commence_time = parser.isoparse(score_item['commence_time'])
                if timezone.is_naive(commence_time):
                    commence_time = timezone.make_aware(commence_time, timezone.get_current_timezone())

                if score_item.get('completed', False):
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_s = score['score']
                            if score['name'] == fixture.away_team.name: away_s = score['score']
                    
                    fixture.home_team_score = int(home_s) if home_s is not None else None
                    fixture.away_team_score = int(away_s) if away_s is not None else None
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    fixture.last_score_update = now
                    fixture.save()
                    logger.info(f"Task {task_id}: Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) completed. Score: {fixture.home_team_score}-{fixture.away_team_score}. Dispatching settlement chain.")
                    
                    chain(
                        settle_outcomes_for_fixture_task.s(fixture.id),
                        settle_bets_for_fixture_task.s(),
                        settle_tickets_for_fixture_task.s()
                    ).apply_async()
                else:
                    if fixture.status == FootballFixture.FixtureStatus.SCHEDULED and commence_time <= now:
                         fixture.status = FootballFixture.FixtureStatus.LIVE
                         logger.info(f"Task {task_id}: Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) is now LIVE.")
                    
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_s = score['score']
                            if score['name'] == fixture.away_team.name: away_s = score['score']
                    
                    # Only update scores if they are provided, otherwise retain existing
                    fixture.home_team_score = int(home_s) if home_s is not None else fixture.home_team_score
                    fixture.away_team_score = int(away_s) if away_s is not None else fixture.away_team_score

                    fixture.last_score_update = now
                    fixture.save()
                    logger.debug(f"Task {task_id}: Fixture {fixture.id} ({fixture.home_team.name} vs {fixture.away_team.name}) status: {fixture.status}. Current scores: {fixture.home_team_score}-{fixture.away_team_score}.")

    except League.DoesNotExist:
        logger.warning(f"Task {task_id}: League with ID {league_id} not found for score fetching. Skipping.")
    except TheOddsAPIException as e:
        logger.error(f"Task {task_id}: API Error fetching scores for league {league_id}: {e} (Status: {e.status_code}, Response: '{e.response_text or e.response_json}'). Retrying...")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Task {task_id}: Unexpected error fetching scores for league {league_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id):
    """(Sub-task) Settles the result status of all market outcomes for a finished fixture."""
    task_id = self.request.id
    logger.info(f"Task {task_id}: Starting outcome settlement for fixture ID: {fixture_id}.")
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, status=FootballFixture.FixtureStatus.FINISHED)
        home_score, away_score = fixture.home_team_score, fixture.away_team_score

        if home_score is None or away_score is None:
            logger.warning(f"Task {task_id}: Cannot settle outcomes for fixture {fixture_id}: scores are missing ({home_score}-{away_score}). Skipping.")
            return

        outcomes_to_update = []
        for market in fixture.markets.prefetch_related('outcomes'):
            logger.debug(f"Task {task_id}: Processing market '{market.api_market_key}' for fixture {fixture_id}.")
            for outcome in market.outcomes.filter(result_status='PENDING'):
                new_status = 'LOST' # Default to lost
                
                # Head-to-Head (H2H)
                if market.api_market_key == 'h2h':
                    if (outcome.outcome_name == fixture.home_team.name and home_score > away_score) or \
                       (outcome.outcome_name == fixture.away_team.name and away_score > home_score):
                        new_status = 'WON'
                    elif outcome.outcome_name.lower() == 'draw' and home_score == away_score:
                        new_status = 'WON'
                
                # Totals (Over/Under)
                elif market.api_market_key == 'totals' and outcome.point_value is not None:
                    total_score = home_score + away_score
                    if 'over' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score > outcome.point_value else ('PUSH' if total_score == outcome.point_value else 'LOST')
                    elif 'under' in outcome.outcome_name.lower():
                        new_status = 'WON' if total_score < outcome.point_value else ('PUSH' if total_score == outcome.point_value else 'LOST')
                
                # Spreads (Handicap)
                elif market.api_market_key == 'spreads' and outcome.point_value is not None:
                    if outcome.outcome_name == fixture.home_team.name: 
                        effective_home_score = home_score + outcome.point_value 
                        new_status = 'WON' if effective_home_score > away_score else ('PUSH' if effective_home_score == away_score else 'LOST')
                    elif outcome.outcome_name == fixture.away_team.name:
                        effective_away_score = away_score + outcome.point_value 
                        new_status = 'WON' if effective_away_score > home_score else ('PUSH' if effective_away_score == home_score else 'LOST')

                # Both Teams To Score (BTTS)
                elif market.api_market_key == 'btts':
                    both_scored = home_score > 0 and away_score > 0
                    if (outcome.outcome_name == 'Yes' and both_scored) or \
                       (outcome.outcome_name == 'No' and not both_scored):
                        new_status = 'WON'
                
                # Double Chance
                elif market.api_market_key == 'double_chance':
                    if outcome.outcome_name == f"{fixture.home_team.name}/Draw":
                        if home_score > away_score or home_score == away_score:
                            new_status = 'WON'
                    elif outcome.outcome_name == f"{fixture.away_team.name}/Draw":
                        if away_score > home_score or home_score == away_score:
                            new_status = 'WON'
                    elif outcome.outcome_name == f"{fixture.home_team.name}/{fixture.away_team.name}":
                        if home_score > away_score or away_score > home_score:
                            new_status = 'WON'
                
                # Full Time Result
                elif market.api_market_key == 'full_time_result':
                    if (outcome.outcome_name == fixture.home_team.name and home_score > away_score) or \
                       (outcome.outcome_name == fixture.away_team.name and away_score > home_score) or \
                       (outcome.outcome_name.lower() == 'draw' and home_score == away_score):
                        new_status = 'WON'

                if new_status != 'PENDING' and outcome.result_status == 'PENDING':
                    outcome.result_status = new_status
                    outcomes_to_update.append(outcome)
                    logger.debug(f"Task {task_id}: Outcome '{outcome.outcome_name}' for market '{market.api_market_key}' set to {new_status}.")
        
        if outcomes_to_update:
            MarketOutcome.objects.bulk_update(outcomes_to_update, ['result_status'])
            logger.info(f"Task {task_id}: Settlement: Marked {len(outcomes_to_update)} outcomes for fixture {fixture_id}.")
        else:
            logger.info(f"Task {task_id}: Settlement: No pending outcomes to update for fixture {fixture_id}.")
        return fixture_id
    except FootballFixture.DoesNotExist:
        logger.warning(f"Task {task_id}: Cannot settle outcomes: fixture {fixture_id} not found or not finished. Skipping.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Error settling outcomes for fixture {fixture_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id):
    """(Sub-task) Settles all individual bets for a fixture."""
    task_id = self.request.id
    if not fixture_id:
        logger.warning(f"Task {task_id}: fixture_id is None for bet settlement. Skipping.")
        return None
    logger.info(f"Task {task_id}: Starting bet settlement for fixture ID: {fixture_id}.")
    try:
        bets_to_settle = Bet.objects.filter(
            market_outcome__market__fixture_display_id=fixture_id, 
            status='PENDING'
        ).select_related('market_outcome')
        logger.debug(f"Task {task_id}: Found {bets_to_settle.count()} pending bets for fixture {fixture_id}.")

        updated_bets = []
        for bet in bets_to_settle:
            if bet.market_outcome.result_status != 'PENDING':
                original_status = bet.status
                bet.status = bet.market_outcome.result_status
                updated_bets.append(bet)
                logger.debug(f"Task {task_id}: Bet {bet.id} status changed from {original_status} to {bet.status} (Outcome: {bet.market_outcome.id}).")
        
        if updated_bets:
            Bet.objects.bulk_update(updated_bets, ['status'])
            logger.info(f"Task {task_id}: Settlement: Settled {len(updated_bets)} bets for fixture {fixture_id}.")
        else:
            logger.info(f"Task {task_id}: Settlement: No bets needed status update for fixture {fixture_id}.")
        return fixture_id
    except Exception as e:
        logger.exception(f"Task {task_id}: Error settling bets for fixture {fixture_id}. Retrying...")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id):
    """(Sub-task) Settles all bet tickets related to a fixture."""
    task_id = self.request.id
    if not fixture_id:
        logger.warning(f"Task {task_id}: fixture_id is None for ticket settlement. Skipping.")
        return None
    logger.info(f"Task {task_id}: Starting ticket settlement for fixture ID: {fixture_id}.")
    try:
        ticket_ids_to_check = BetTicket.objects.filter(
            bets__market_outcome__market__fixture_display_id=fixture_id
        ).distinct().values_list('id', flat=True)
        logger.debug(f"Task {task_id}: Found {len(ticket_ids_to_check)} distinct tickets related to fixture {fixture_id}.")

        for ticket_id in ticket_ids_to_check:
            ticket = BetTicket.objects.prefetch_related('bets__market_outcome').get(id=ticket_id)
            
            if all(b.status != 'PENDING' for b in ticket.bets.all()):
                original_status = ticket.status
                ticket.settle_ticket() # This method should contain the logic to set ticket status and potentially credit user
                logger.info(f"Task {task_id}: Ticket {ticket_id} settled. Status changed from {original_status} to {ticket.status}. Customer: {ticket.customer.id}.")
            else:
                logger.info(f"Task {task_id}: Ticket {ticket_id} still has pending bets, not yet settled. Current status: {ticket.status}.")

        logger.info(f"Task {task_id}: Settlement: Checked {len(ticket_ids_to_check)} tickets for fixture {fixture_id}.")
    except Exception as e:
        logger.exception(f"Task {task_id}: Error settling tickets for fixture {fixture_id}. Retrying...")
        raise self.retry(exc=e)