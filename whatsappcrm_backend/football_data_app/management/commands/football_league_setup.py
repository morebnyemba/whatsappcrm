# football_data_app/management/commands/football_league_setup.py
from django.core.management.base import BaseCommand
from django.db import transaction
from football_data_app.models import League
from football_data_app.apifootball_client import APIFootballClient
import logging

logger = logging.getLogger(__name__)

def setup_football_leagues():
    """
    Fetches and sets up football leagues from APIFootball.com.
    This is optimized to use minimal API credits and is safe to run multiple times.
    It uses `update_or_create` to prevent duplicates and keep data fresh.
    """
    client = APIFootballClient()
    logger.info("Starting football leagues setup with APIFootball.com.")
    
    try:
        # Fetch leagues data
        leagues_data = client.get_leagues()
        if not leagues_data:
            logger.error("No leagues data received from APIFootball API")
            return
            
        created_count = 0
        updated_count = 0
        
        # Use a transaction to ensure all or nothing
        with transaction.atomic():
            for item in leagues_data:
                league_id = item.get('league_id')
                league_name = item.get('league_name')
                
                # Skip if essential data is missing
                if not league_id or not league_name:
                    continue
                
                # Use update_or_create to prevent duplicates and keep names fresh
                _, created = League.objects.update_or_create(
                    api_id=league_id,
                    defaults={
                        'name': league_name,
                        'sport_key': 'soccer',
                        'sport_group_name': 'Football',
                        'short_name': league_name,
                        'country_id': item.get('country_id'),
                        'country_name': item.get('country_name'),
                        'league_season': item.get('league_season'),
                        'logo_url': item.get('league_logo'),
                        'active': True,
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
    help = 'Fetches and updates the list of active football leagues from APIFootball.com.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting the football league setup process with APIFootball.com..."))
        setup_football_leagues()
        self.stdout.write(self.style.SUCCESS("Football league setup process completed."))