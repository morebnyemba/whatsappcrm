import logging
from datetime import timedelta
from typing import List, Optional

from celery import shared_task, chain, group
from django.db import transaction, models
from django.utils import timezone
from dateutil import parser

from .models import (
    League,
    FootballFixture,
    Bookmaker,
    MarketCategory,
    Market,
    MarketOutcome,
    Team
)
from .the_odds_api_client import TheOddsAPIClient, TheOddsAPIException

logger = logging.getLogger(__name__)

# Configuration
ODDS_LEAD_TIME_DAYS = 7
DEFAULT_REGIONS = "uk,eu,us,au"
MAIN_MARKETS = "h2h,totals"
ADDITIONAL_MARKETS = "btts,alternate_totals,h2h_3way"
BOOKMAKERS = "pinnacle,unibet,draftkings"
BATCH_SIZE = 10
STALENESS_MINUTES = 30
MAX_RETRIES = 3
RETRY_DELAY = 300  # seconds

def _parse_outcome_details(outcome_name: str, market_key: str) -> tuple:
    """Parse outcome name and point value from API response."""
    name_part = outcome_name
    point_part = None
    
    if market_key in ['totals', 'spreads', 'alternate_totals']:
        try:
            parts = outcome_name.split()
            last_part = parts[-1]
            if last_part.replace('.', '', 1).lstrip('+-').isdigit():
                point_part = float(last_part)
                name_part = " ".join(parts[:-1]) or outcome_name
        except (ValueError, IndexError):
            logger.debug(f"Couldn't parse point from outcome: {outcome_name}")
    
    return name_part, point_part

def _get_active_fixtures(league: League) -> List[str]:
    """Get event IDs needing odds updates with staleness check."""
    now = timezone.now()
    stale_cutoff = now - timedelta(minutes=STALENESS_MINUTES)
    
    return list(FootballFixture.objects.filter(
        league=league,
        status=FootballFixture.FixtureStatus.SCHEDULED,
        start_time__range=(now, now + timedelta(days=ODDS_LEAD_TIME_DAYS))
    ).filter(
        models.Q(last_odds_update__isnull=True) |
        models.Q(last_odds_update__lt=stale_cutoff)
    ).values_list('api_id', flat=True)[:200])  # Safety limit

def _process_bookmaker_data(fixture: FootballFixture, bookmaker_data: dict, market_types: List[str]):
    """Process and save bookmaker's market data."""
    try:
        bookmaker, _ = Bookmaker.objects.get_or_create(
            api_id=bookmaker_data['key'],
            defaults={'name': bookmaker_data['title']}
        )
        
        for market_data in bookmaker_data.get('markets', []):
            market_key = market_data['key']
            if market_key not in market_types:
                continue
                
            # Delete existing before creating new
            Market.objects.filter(
                fixture=fixture,
                bookmaker=bookmaker,
                api_market_key=market_key
            ).delete()
            
            category, _ = MarketCategory.objects.get_or_create(
                name=market_key.replace("_", " ").title()
            )
            
            market = Market.objects.create(
                fixture=fixture,
                bookmaker=bookmaker,
                category=category,
                api_market_key=market_key,
                last_updated=parser.parse(market_data['last_update'])
            )
            
            for outcome_data in market_data.get('outcomes', []):
                name, point = _parse_outcome_details(outcome_data['name'], market_key)
                MarketOutcome.objects.create(
                    market=market,
                    outcome_name=name,
                    odds=outcome_data['price'],
                    point_value=point
                )
                
    except Exception as e:
        logger.error(f"Error processing bookmaker data: {str(e)}")
        raise  # Re-raise to trigger task retry

@shared_task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=RETRY_DELAY)
def update_league_odds(self, league_id: int):
    """Main task to update all odds for a league."""
    try:
        league = League.objects.get(id=league_id)
        event_ids = _get_active_fixtures(league)
        
        if not event_ids:
            logger.info(f"No events need updating for {league.name}")
            return
            
        # Create parallel tasks
        tasks = []
        
        # Main markets in batches
        for i in range(0, len(event_ids), BATCH_SIZE):
            tasks.append(
                fetch_main_markets.si(
                    league_id=league.id,
                    event_ids=event_ids[i:i+BATCH_SIZE]
                )
            )
        
        # Additional markets individually
        for event_id in event_ids:
            tasks.append(
                fetch_additional_markets.si(event_id=event_id)
            )
        
        # Execute all in parallel
        group(tasks).apply_async()
        
    except League.DoesNotExist:
        logger.error(f"League {league_id} not found")
    except Exception as e:
        logger.error(f"Failed league update {league_id}: {str(e)}")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=RETRY_DELAY)
def fetch_main_markets(self, league_id: int, event_ids: List[str]):
    """Fetch and process main markets for a batch."""
    client = TheOddsAPIClient()
    
    try:
        league = League.objects.get(id=league_id)
        odds_data = client.get_odds_batch(
            sport_key=league.api_id,
            regions=DEFAULT_REGIONS,
            markets=MAIN_MARKETS,
            event_ids=event_ids,
            bookmakers=BOOKMAKERS
        )
        
        if not odds_data:
            logger.warning(f"No odds for batch of {len(event_ids)} events")
            return
            
        fixtures = {f.api_id: f for f in FootballFixture.objects.filter(api_id__in=event_ids)}
        
        with transaction.atomic():
            for event_data in odds_data:
                if event_data['id'] not in fixtures:
                    continue
                    
                fixture = fixtures[event_data['id']]
                
                for bookmaker in event_data.get('bookmakers', []):
                    _process_bookmaker_data(fixture, bookmaker, MAIN_MARKETS.split(','))
                
                fixture.last_odds_update = timezone.now()
                fixture.save()
                
    except TheOddsAPIException as e:
        logger.error(f"API error for batch: {str(e)}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Failed batch processing: {str(e)}")
        raise self.retry(exc=e)

@shared_task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=RETRY_DELAY)
def fetch_additional_markets(self, event_id: str):
    """Fetch and process additional markets for single event."""
    client = TheOddsAPIClient()
    
    try:
        fixture = FootballFixture.objects.get(api_id=event_id)
        odds_data = client.get_event_odds(
            event_id=event_id,
            regions=DEFAULT_REGIONS,
            markets=ADDITIONAL_MARKETS,
            bookmakers=BOOKMAKERS
        )
        
        if not odds_data:
            logger.warning(f"No additional markets for {event_id}")
            return
            
        with transaction.atomic():
            for bookmaker in odds_data.get('bookmakers', []):
                _process_bookmaker_data(fixture, bookmaker, ADDITIONAL_MARKETS.split(','))
            
            fixture.last_odds_update = timezone.now()
            fixture.save()
            
    except FootballFixture.DoesNotExist:
        logger.warning(f"Fixture {event_id} not found")
    except TheOddsAPIException as e:
        logger.error(f"API error for event {event_id}: {str(e)}")
        raise self.retry(exc=e)
    except Exception as e:
        logger.error(f"Failed event processing {event_id}: {str(e)}")
        raise self.retry(exc=e)

@shared_task
def update_all_leagues_odds():
    """Orchestrate odds updates for all active leagues."""
    league_ids = League.objects.filter(active=True).values_list('id', flat=True)
    
    if not league_ids:
        logger.info("No active leagues to update")
        return
        
    group(
        update_league_odds.si(league_id=league_id)
        for league_id in league_ids
    ).apply_async()

@shared_task(bind=True, max_retries=3, default_retry_delay=900)
def update_scores(self):
    """Update scores for all active leagues."""
    client = TheOddsAPIClient()
    
    for league in League.objects.filter(active=True):
        try:
            recent_fixtures = FootballFixture.objects.filter(
                league=league,
                status=FootballFixture.FixtureStatus.SCHEDULED,
                start_time__lte=timezone.now()
            ).values_list('api_id', flat=True)
            
            if not recent_fixtures:
                continue
                
            scores_data = client.get_scores(
                sport_key=league.api_id,
                event_ids=list(recent_fixtures)
            )
            
            if not scores_data:
                continue
                
            _process_scores(scores_data)
            
        except TheOddsAPIException as e:
            logger.error(f"API error updating scores for {league.name}: {str(e)}")
            continue
        except Exception as e:
            logger.error(f"Failed score update for {league.name}: {str(e)}")
            continue

def _process_scores(scores_data: List[dict]):
    """Process and save score updates."""
    fixtures = {f.api_id: f for f in FootballFixture.objects.filter(
        api_id__in=[s['id'] for s in scores_data]
    )}
    
    with transaction.atomic():
        for score_data in scores_data:
            if score_data['id'] not in fixtures:
                continue
                
            fixture = fixtures[score_data['id']]
            
            # Update scores
            if score_data.get('scores'):
                for team_score in score_data['scores']:
                    if team_score['name'] == fixture.home_team.name:
                        fixture.home_score = int(team_score['score'])
                    elif team_score['name'] == fixture.away_team.name:
                        fixture.away_score = int(team_score['score'])
            
            # Update status
            if score_data.get('completed', False):
                fixture.status = FootballFixture.FixtureStatus.FINISHED
                fixture.save()
                _settle_markets(fixture)
            else:
                fixture.status = FootballFixture.FixtureStatus.LIVE
                fixture.save()

def _settle_markets(fixture: FootballFixture):
    """Determine and save market outcomes."""
    if fixture.home_score is None or fixture.away_score is None:
        return
        
    with transaction.atomic():
        for market in fixture.markets.all():
            for outcome in market.outcomes.all():
                outcome.result_status = _determine_outcome_status(
                    outcome,
                    fixture.home_score,
                    fixture.away_score
                )
                outcome.save()

def _determine_outcome_status(outcome: MarketOutcome, home_score: int, away_score: int) -> str:
    """Determine if outcome won based on market type."""
    market_type = outcome.market.api_market_key
    
    if market_type == 'h2h':
        if outcome.outcome_name.lower() == 'draw':
            return 'WON' if home_score == away_score else 'LOST'
        return 'WON' if (
            (outcome.outcome_name == outcome.market.fixture.home_team.name and home_score > away_score) or
            (outcome.outcome_name == outcome.market.fixture.away_team.name and away_score > home_score)
        ) else 'LOST'
        
    elif market_type in ['totals', 'alternate_totals'] and outcome.point_value:
        total = home_score + away_score
        if 'over' in outcome.outcome_name.lower():
            return 'WON' if total > outcome.point_value else 'PUSH' if total == outcome.point_value else 'LOST'
        elif 'under' in outcome.outcome_name.lower():
            return 'WON' if total < outcome.point_value else 'PUSH' if total == outcome.point_value else 'LOST'
    
    elif market_type == 'btts':
        if outcome.outcome_name.lower() == 'yes':
            return 'WON' if home_score > 0 and away_score > 0 else 'LOST'
        return 'WON' if home_score == 0 or away_score == 0 else 'LOST'
    
    return 'LOST'  # Default case