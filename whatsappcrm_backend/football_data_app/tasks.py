# football_data_app/tasks.py
import logging
from django.conf import settings
from celery import shared_task, chain
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser
from datetime import timedelta

from .models import League, FootballFixture, Bookmaker, MarketCategory, Market, MarketOutcome, Team
from customer_data.models import Bet, BetTicket
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# --- Configuration ---
ODDS_LEAD_TIME_DAYS = getattr(settings, 'THE_ODDS_API_LEAD_TIME_DAYS', 7)
DEFAULT_ODDS_API_REGIONS = getattr(settings, 'THE_ODDS_API_DEFAULT_REGIONS', "uk,eu,us,au")
DEFAULT_ODDS_API_MARKETS = getattr(settings, 'THE_ODDS_API_DEFAULT_MARKETS', "h2h,totals,spreads")
ODDS_IMMINENT_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_IMMINENT_STALENESS_MINUTES', 15)
ODDS_UPCOMING_STALENESS_MINUTES = getattr(settings, 'THE_ODDS_API_UPCOMING_STALENESS_MINUTES', 60)
EVENT_DISCOVERY_STALENESS_HOURS = getattr(settings, 'THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS', 6)
ODDS_FETCH_EVENT_BATCH_SIZE = getattr(settings, 'THE_ODDS_API_BATCH_SIZE', 10)
DAYS_FROM_FOR_SCORES = getattr(settings, 'THE_ODDS_API_DAYS_FROM_SCORES', 3)

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
            logger.warning(f"Could not parse point from outcome: '{outcome_name_api}' for market '{market_key_api}'")
    return name_part, point_part

# --- Data Fetching Tasks (Now with Logo Logic) ---
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_and_update_leagues_task(self):
    """Fetches and updates football leagues, now including their logos."""
    client, created_count, updated_count = TheOddsAPIClient(), 0, 0
    logger.info("Starting league fetch task.")
    try:
        sports_data = client.get_sports(all_sports=True)
        for item in sports_data:
            if 'soccer' not in item.get('key', ''): continue
            
            _, created = League.objects.update_or_create(
                api_id=item['key'],
                defaults={
                    'name': item.get('title', 'Unknown League'), 
                    'sport_key': 'soccer', 
                    'active': True,
                    'logo_url': item.get('logo') # <-- ADDED LOGO
                }
            )
            if created: created_count += 1
            else: updated_count += 1
        logger.info(f"Leagues Task: {created_count} created, {updated_count} updated.")
    except TheOddsAPIException as e:
        logger.error(f"API Error fetching leagues: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception("Unexpected error in league fetching task.")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def fetch_events_for_league_task(self, league_id):
    """Fetches and updates events (fixtures), now including team logos."""
    client, created_count, updated_count = TheOddsAPIClient(), 0, 0
    try:
        league = League.objects.get(id=league_id)
        logger.info(f"Fetching events for league: {league.name}")
        events_data = client.get_events(sport_key=league.api_id)
        for item in events_data:
            home_obj, _ = Team.objects.update_or_create(name=item['home_team'], defaults={'logo_url': item.get('home_team_logo')})
            away_obj, _ = Team.objects.update_or_create(name=item['away_team'], defaults={'logo_url': item.get('away_team_logo')})
            
            _, created = FootballFixture.objects.update_or_create(
                api_id=item['id'],
                defaults={
                    'league': league, 'home_team': home_obj, 'away_team': away_obj,
                    'match_date': parser.isoparse(item['commence_time'])
                }
            )
            if created: created_count += 1
            else: updated_count += 1
        league.last_fetched_events = timezone.now()
        league.save(update_fields=['last_fetched_events'])
        logger.info(f"Events for {league.name}: {created_count} created, {updated_count} updated.")
    except League.DoesNotExist:
        logger.warning(f"League with ID {league_id} not found for event fetching.")
    except TheOddsAPIException as e:
        logger.error(f"API Error fetching events for league {league_id}: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Unexpected error fetching events for league {league_id}.")
        raise self.retry(exc=e)

# --- The rest of the tasks remain the same ---
# (fetch_odds_for_event_batch_task, fetch_scores_for_league_task, settlement tasks, and orchestrator)
# They are included below for completeness.

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def fetch_odds_for_event_batch_task(self, sport_key, event_ids):
    """Fetches and updates odds for a batch of events."""
    client = TheOddsAPIClient()
    logger.info(f"Fetching odds for {len(event_ids)} events in {sport_key}.")
    try:
        odds_data = client.get_odds(sport_key=sport_key, event_ids=event_ids, regions=DEFAULT_ODDS_API_REGIONS, markets=DEFAULT_ODDS_API_MARKETS)
        fixtures = FootballFixture.objects.in_bulk([item['id'] for item in odds_data], field_name='api_id')

        with transaction.atomic():
            for event_data in odds_data:
                fixture = fixtures.get(event_data['id'])
                if not fixture: continue
                
                Market.objects.filter(fixture_display=fixture).delete()
                for bookmaker_data in event_data.get('bookmakers', []):
                    bookmaker, _ = Bookmaker.objects.get_or_create(api_bookmaker_key=bookmaker_data['key'], defaults={'name': bookmaker_data['title']})
                    for market_data in bookmaker_data.get('markets', []):
                        market_key = market_data['key']
                        category, _ = MarketCategory.objects.get_or_create(name=market_key.replace("_", " ").title())
                        market_instance = Market.objects.create(
                            fixture_display=fixture, bookmaker=bookmaker, category=category,
                            api_market_key=market_key, last_updated_odds_api=parser.isoparse(market_data['last_update'])
                        )
                        for outcome_data in market_data.get('outcomes', []):
                            name, point = _parse_outcome_details(outcome_data['name'], market_key)
                            MarketOutcome.objects.create(market=market_instance, outcome_name=name, odds=outcome_data['price'], point_value=point)

        FootballFixture.objects.filter(api_id__in=event_ids).update(last_odds_update=timezone.now())
        logger.info(f"Successfully processed odds for {len(fixtures)} fixtures.")
    except TheOddsAPIException as e:
        logger.error(f"API Error fetching odds for {sport_key}: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Unexpected error fetching odds for {sport_key}.")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=2, default_retry_delay=900)
def fetch_scores_for_league_task(self, league_id):
    """Fetches scores for completed or live fixtures in a league."""
    now = timezone.now()
    try:
        league = League.objects.get(id=league_id)
        fixtures_to_check = FootballFixture.objects.filter(
            models.Q(league=league, status='LIVE') | models.Q(league=league, status='SCHEDULED', match_date__lt=now),
            models.Q(last_score_update__isnull=True) | models.Q(last_score_update__lt=now - timedelta(minutes=10))
        ).values_list('api_id', flat=True)

        if not fixtures_to_check.exists():
            logger.info(f"No fixtures need score updates for league {league.name}.")
            return
            
        client = TheOddsAPIClient()
        scores_data = client.get_scores(sport_key=league.api_id, event_ids=list(fixtures_to_check))
        
        for score_item in scores_data:
            with transaction.atomic():
                fixture = FootballFixture.objects.select_for_update().get(api_id=score_item['id'])
                is_completed = score_item.get('completed', False)
                
                if is_completed:
                    home_s, away_s = None, None
                    if score_item.get('scores'):
                        for score in score_item['scores']:
                            if score['name'] == fixture.home_team.name: home_s = score['score']
                            if score['name'] == fixture.away_team.name: away_s = score['score']
                    fixture.home_team_score = int(home_s) if home_s else None
                    fixture.away_team_score = int(away_s) if away_s else None
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    fixture.last_score_update = now
                    fixture.save()
                    
                    chain(
                        settle_outcomes_for_fixture_task.s(fixture.id),
                        settle_bets_for_fixture_task.s(),
                        settle_tickets_for_fixture_task.s()
                    ).apply_async()
                else:
                    fixture.status = FootballFixture.FixtureStatus.LIVE
                    fixture.last_score_update = now
                    fixture.save()
                    
    except League.DoesNotExist:
        logger.warning(f"League {league_id} not found for score fetching.")
    except TheOddsAPIException as e:
        logger.error(f"API error fetching scores for league {league_id}: {e}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception(f"Unexpected error fetching scores for league {league_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_outcomes_for_fixture_task(self, fixture_id):
    """Settles the result status of all market outcomes for a finished fixture."""
    try:
        fixture = FootballFixture.objects.get(id=fixture_id, status=FootballFixture.FixtureStatus.FINISHED)
        home_score, away_score = fixture.home_team_score, fixture.away_team_score

        if home_score is None or away_score is None:
            logger.warning(f"Cannot settle outcomes for fixture {fixture_id}: scores are missing.")
            return

        for market in fixture.markets.prefetch_related('outcomes'):
            for outcome in market.outcomes.filter(result_status='PENDING'):
                # Your settlement logic here
                outcome.result_status = 'WON' 
                outcome.save()
        
        logger.info(f"Settlement: Marked outcomes for fixture {fixture_id}.")
        return fixture_id
    except FootballFixture.DoesNotExist:
        logger.warning(f"Cannot settle outcomes: fixture {fixture_id} not found or not finished.")
    except Exception as e:
        logger.exception(f"Error settling outcomes for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_bets_for_fixture_task(self, fixture_id):
    if not fixture_id: return
    try:
        bets_to_settle = Bet.objects.filter(market_outcome__market__fixture_display_id=fixture_id, status='PENDING')
        for bet in bets_to_settle:
            if bet.market_outcome.result_status != 'PENDING':
                bet.status = bet.market_outcome.result_status
                bet.save()
                if bet.status == 'WON':
                    pass
        logger.info(f"Settlement: Settled bets for fixture {fixture_id}.")
        return fixture_id
    except Exception as e:
        logger.exception(f"Error settling bets for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(bind=True)
def settle_tickets_for_fixture_task(self, fixture_id):
    if not fixture_id: return
    try:
        ticket_ids_to_check = BetTicket.objects.filter(bets__market_outcome__market__fixture_display_id=fixture_id).distinct().values_list('id', flat=True)
        for ticket_id in ticket_ids_to_check:
            ticket = BetTicket.objects.get(id=ticket_id)
            if all(b.status != 'PENDING' for b in ticket.bets.all()):
                ticket.settle_ticket()
        logger.info(f"Settlement: Checked tickets for fixture {fixture_id}.")
    except Exception as e:
        logger.exception(f"Error settling tickets for fixture {fixture_id}.")
        raise self.retry(exc=e)

@shared_task(name="football_data_app.run_the_odds_api_full_update")
def run_the_odds_api_full_update_task():
    now = timezone.now()
    logger.info("Orchestrator task started.")
    
    fetch_and_update_leagues_task.apply_async()
    
    for league in League.objects.filter(active=True):
        if not league.last_fetched_events or league.last_fetched_events < (now - timedelta(hours=EVENT_DISCOVERY_STALENESS_HOURS)):
            fetch_events_for_league_task.apply_async(args=[league.id])

        stale_fixtures_q = models.Q(
            models.Q(match_date__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))),
            models.Q(last_odds_update__isnull=True) | models.Q(last_odds_update__lt=now - timedelta(minutes=ODDS_UPCOMING_STALENESS_MINUTES))
        )
        event_ids = list(FootballFixture.objects.filter(league=league, status='SCHEDULED').filter(stale_fixtures_q).values_list('api_id', flat=True))
        
        for i in range(0, len(event_ids), ODDS_FETCH_EVENT_BATCH_SIZE):
            batch = event_ids[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
            fetch_odds_for_event_batch_task.apply_async(args=[league.api_id, batch])

        fetch_scores_for_league_task.apply_async(args=[league.id])
        
    logger.info("Orchestrator task finished dispatching jobs.")