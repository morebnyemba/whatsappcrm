from django.core.management.base import BaseCommand
from football_data_app.models import League
from football_data_app.the_odds_api_client import TheOddsAPIClient
import logging

logger = logging.getLogger(__name__)

def setup_football_leagues():
    """
    Function to fetch and setup only football leagues.
    This is optimized to use minimal API credits by:
    1. Only fetching football leagues
    2. Making a single API call
    3. Creating leagues in bulk
    """
    client = TheOddsAPIClient()
    logger.info("Starting football leagues setup.")
    
    try:
        # Fetch sports data
        sports_data = client.get_sports(all_sports=True)
        if not sports_data:
            logger.error("No sports data received from API")
            return
            
        # Filter and prepare football leagues
        football_leagues = []
        for item in sports_data:
            key = item.get('key')
            title = item.get('title')
            
            # Only process football/soccer leagues
            if not key or not title or not key.startswith('soccer_'):
                continue
                
            football_leagues.append(League(
                sport_key=key,
                name=title,
                sport_title=title,
                active=True
            ))
            
        # Bulk create leagues
        if football_leagues:
            League.objects.bulk_create(football_leagues)
            logger.info(f"Successfully created {len(football_leagues)} football leagues")
        else:
            logger.warning("No football leagues found in the API response")
            
    except Exception as e:
        logger.exception("Error setting up football leagues")
        raise

class Command(BaseCommand):
    help = 'Sets up football leagues from The Odds API'

    def handle(self, *args, **options):
        setup_football_leagues() 