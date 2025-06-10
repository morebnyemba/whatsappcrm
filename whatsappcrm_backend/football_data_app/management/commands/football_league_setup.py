# football_data_app/management/commands/football_league_setup.py
from django.core.management.base import BaseCommand
from django.db import transaction
from football_data_app.models import League
from football_data_app.the_odds_api_client import TheOddsAPIClient
import logging

logger = logging.getLogger(__name__)

def setup_football_leagues():
    """
    Fetches and sets up only football leagues from The Odds API.
    This is optimized to use minimal API credits and is safe to run multiple times.
    It uses `update_or_create` to prevent duplicates and keep data fresh.
    """
    client = TheOddsAPIClient()
    logger.info("Starting football leagues setup.")
    
    try:
        # Fetch sports data
        sports_data = client.get_sports(all_sports=True)
        if not sports_data:
            logger.error("No sports data received from API")
            return
            
        created_count = 0
        updated_count = 0
        
        # Use a transaction to ensure all or nothing
        with transaction.atomic():
            for item in sports_data:
                key = item.get('key')
                title = item.get('title')
                
                # Only process football/soccer leagues
                if not key or not title or not key.startswith('soccer_'):
                    continue
                
                # Use update_or_create to prevent duplicates and keep names fresh
                _, created = League.objects.update_or_create(
                    api_id=key,  # Correct field for the unique API key
                    defaults={
                        'name': title,
                        'sport_key': 'soccer', # Hardcode the sport key as per logic
                        'active': True,
                        'logo_url': item.get('logo') # Now correctly handles the logo
                    }
                )
                
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                    
        logger.info(f"Football leagues setup finished. Created: {created_count}, Updated: {updated_count}.")
            
    except Exception as e:
        logger.exception("An error occurred during football leagues setup")
        # Do not re-raise the exception to allow the command to exit gracefully
        # The exception is already logged.

class Command(BaseCommand):
    help = 'Fetches and updates the list of active football leagues from The Odds API.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting the football league setup process..."))
        setup_football_leagues()
        self.stdout.write(self.style.SUCCESS("Football league setup process completed."))