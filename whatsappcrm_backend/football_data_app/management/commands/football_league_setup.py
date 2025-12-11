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
    try:
        client = APIFootballClient()
    except ValueError as e:
        logger.error(f"Failed to initialize APIFootball client: {e}")
        logger.error(
            "Please configure your API key by either:"
            "\n  1. Setting API_FOOTBALL_KEY in your .env file"
            "\n  2. Adding a Configuration entry in Django admin (provider_name='APIFootball')"
            "\n  Get your API key at: https://apifootball.com/"
        )
        return
    
    logger.info("Starting football leagues setup with APIFootball.com.")
    
    try:
        # Fetch leagues data
        leagues_data = client.get_leagues()
        if not leagues_data:
            logger.error("No leagues data received from APIFootball API")
            logger.error(
                "This could mean:"
                "\n  • API returned an empty list (no leagues available)"
                "\n  • Your API plan may not include league data"
                "\n  • Check your subscription at: https://apifootball.com/dashboard"
            )
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
        logger.error(
            "\n=== TROUBLESHOOTING GUIDE ==="
            "\n1. Verify your API key is correct:"
            "\n   • Check .env file for API_FOOTBALL_KEY"
            "\n   • Or verify Configuration in Django admin"
            "\n   • Get/verify key at: https://apifootball.com/dashboard"
            "\n"
            "\n2. Check your API subscription:"
            "\n   • Ensure your account is active"
            "\n   • Verify your plan includes the 'get_leagues' endpoint"
            "\n   • Check remaining API calls quota"
            "\n"
            "\n3. Test API connectivity:"
            "\n   • Run: python manage.py check_football_setup"
            "\n   • This will test your API connection"
            "\n"
            "\nFor more help, visit: https://apifootball.com/documentation/"
        )
        # Do not re-raise the exception to allow the command to exit gracefully
        # The exception is already logged.

class Command(BaseCommand):
    help = 'Fetches and updates the list of active football leagues from APIFootball.com.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting the football league setup process with APIFootball.com..."))
        setup_football_leagues()
        self.stdout.write(self.style.SUCCESS("Football league setup process completed."))