# football_data_app/management/commands/football_league_setup_v3.py
from django.core.management.base import BaseCommand
from django.db import transaction
from football_data_app.models import League
from football_data_app.api_football_v3_client import APIFootballV3Client, APIFootballV3Exception
import logging

logger = logging.getLogger(__name__)

def setup_football_leagues_v3():
    """
    Fetches and sets up football leagues from API-Football v3 (api-football.com).
    This is optimized to use minimal API credits and is safe to run multiple times.
    It uses `update_or_create` to prevent duplicates and keep data fresh.
    """
    try:
        client = APIFootballV3Client()
    except ValueError as e:
        logger.error(f"Failed to initialize API-Football v3 client: {e}")
        logger.error(
            "Please configure your API key by either:"
            "\n  1. Setting API_FOOTBALL_V3_KEY in your .env file"
            "\n  2. Adding a Configuration entry in Django admin (provider_name='API-Football')"
            "\n  Get your API key at: https://www.api-football.com/"
        )
        return
    
    logger.info("Starting football leagues setup with API-Football v3 (api-football.com).")
    
    try:
        # Fetch leagues data
        leagues_data = client.get_leagues()
        if not leagues_data:
            logger.error("No leagues data received from API-Football v3 API")
            logger.error(
                "This could mean:"
                "\n  • API returned an empty list (no leagues available)"
                "\n  • Your API plan may not include league data"
                "\n  • Check your subscription at: https://www.api-football.com/account"
            )
            return
            
        created_count = 0
        updated_count = 0
        
        # Use a transaction to ensure all or nothing
        with transaction.atomic():
            for item in leagues_data:
                league_info = item.get('league', {})
                country_info = item.get('country', {})
                
                league_id = league_info.get('id')
                league_name = league_info.get('name')
                league_logo = league_info.get('logo')
                country_name = country_info.get('name')
                
                # Skip if essential data is missing
                if not league_id or not league_name:
                    continue
                
                # Use v3_ prefix to distinguish from legacy leagues
                api_id_str = f"v3_{league_id}"
                
                # Use update_or_create to prevent duplicates and keep names fresh
                _, created = League.objects.update_or_create(
                    api_id=api_id_str,
                    defaults={
                        'name': league_name,
                        'sport_key': 'soccer',
                        'sport_group_name': 'Football',
                        'short_name': league_name,
                        'country_name': country_name,
                        'logo_url': league_logo,
                        'active': True,
                    }
                )
                
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                    
        logger.info(f"Football leagues setup finished. Created: {created_count}, Updated: {updated_count}.")
            
    except APIFootballV3Exception as e:
        logger.exception("An API-Football v3 API error occurred during football leagues setup")
        logger.error(
            "\n=== TROUBLESHOOTING GUIDE ==="
            "\n1. Verify your API key is correct:"
            "\n   • Check .env file for API_FOOTBALL_V3_KEY"
            "\n   • Or verify Configuration in Django admin (provider_name='API-Football')"
            "\n   • Get/verify key at: https://www.api-football.com/account"
            "\n"
            "\n2. Check your API subscription:"
            "\n   • Ensure your account is active"
            "\n   • Verify your plan includes the 'leagues' endpoint"
            "\n   • Check remaining API calls quota"
            "\n"
            "\n3. Test API connectivity:"
            "\n   • Run: python manage.py check_football_setup"
            "\n   • This will test your API connection"
            "\n"
            "\nFor more help, visit: https://www.api-football.com/documentation-v3"
        )
    except Exception as e:
        logger.exception("An error occurred during football leagues setup")
        logger.error(
            "\n=== TROUBLESHOOTING GUIDE ==="
            "\n1. Verify your API key is correct:"
            "\n   • Check .env file for API_FOOTBALL_V3_KEY"
            "\n   • Or verify Configuration in Django admin (provider_name='API-Football')"
            "\n   • Get/verify key at: https://www.api-football.com/account"
            "\n"
            "\n2. Check your API subscription:"
            "\n   • Ensure your account is active"
            "\n   • Verify your plan includes the 'leagues' endpoint"
            "\n   • Check remaining API calls quota"
            "\n"
            "\n3. Test API connectivity:"
            "\n   • Run: python manage.py check_football_setup"
            "\n   • This will test your API connection"
            "\n"
            "\nFor more help, visit: https://www.api-football.com/documentation-v3"
        )

class Command(BaseCommand):
    help = 'Fetches and updates the list of active football leagues from API-Football v3 (api-football.com).'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting the football league setup process with API-Football v3 (api-football.com)..."))
        setup_football_leagues_v3()
        self.stdout.write(self.style.SUCCESS("Football league setup process completed."))
