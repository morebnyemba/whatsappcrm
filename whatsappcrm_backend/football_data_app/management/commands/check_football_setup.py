# football_data_app/management/commands/check_football_setup.py
from django.core.management.base import BaseCommand
from django.conf import settings
from football_data_app.models import League, FootballFixture, Configuration
from football_data_app.apifootball_client import APIFootballClient
import os


class Command(BaseCommand):
    help = 'Checks if the football data system is properly configured and ready to run'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("="*80))
        self.stdout.write(self.style.SUCCESS("Football Data System Setup Check"))
        self.stdout.write(self.style.SUCCESS("="*80))
        self.stdout.write("")
        
        errors = []
        warnings = []
        
        # Check 1: API Key Configuration
        self.stdout.write("1. Checking API Key Configuration...")
        api_key_env = os.getenv('API_FOOTBALL_KEY')
        db_config = Configuration.objects.filter(
            provider_name='APIFootball',
            is_active=True
        ).first()
        
        if api_key_env:
            self.stdout.write(self.style.SUCCESS("   ✓ API key found in environment variable"))
        elif db_config and db_config.api_key:
            self.stdout.write(self.style.SUCCESS("   ✓ API key found in database configuration"))
        else:
            errors.append("No APIFootball API key configured")
            self.stdout.write(self.style.ERROR(
                "   ✗ No API key found in environment or database"
            ))
            self.stdout.write(self.style.WARNING(
                "     → Set API_FOOTBALL_KEY in .env or add Configuration in admin"
            ))
        self.stdout.write("")
        
        # Check 2: Leagues in Database
        self.stdout.write("2. Checking Leagues in Database...")
        total_leagues = League.objects.count()
        active_leagues = League.objects.filter(active=True).count()
        
        if total_leagues == 0:
            errors.append("No leagues in database")
            self.stdout.write(self.style.ERROR(
                "   ✗ No leagues found in database"
            ))
            self.stdout.write(self.style.WARNING(
                "     → Run: python manage.py football_league_setup"
            ))
        elif active_leagues == 0:
            warnings.append("No active leagues")
            self.stdout.write(self.style.WARNING(
                f"   ⚠ {total_leagues} leagues found, but none are active"
            ))
            self.stdout.write(self.style.WARNING(
                "     → Activate leagues in Django admin or run football_league_setup"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"   ✓ {active_leagues} active leagues found (out of {total_leagues} total)"
            ))
        self.stdout.write("")
        
        # Check 3: Fixtures
        self.stdout.write("3. Checking Fixtures...")
        fixture_count = FootballFixture.objects.count()
        
        if fixture_count == 0:
            warnings.append("No fixtures in database")
            self.stdout.write(self.style.WARNING(
                "   ⚠ No fixtures found in database"
            ))
            self.stdout.write(self.style.WARNING(
                "     → Fixtures will be fetched automatically by scheduled tasks"
            ))
            self.stdout.write(self.style.WARNING(
                "     → Or manually trigger: run_apifootball_full_update task"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"   ✓ {fixture_count} fixtures in database"
            ))
        self.stdout.write("")
        
        # Check 4: API Connectivity (optional, only if we have a key)
        if api_key_env or (db_config and db_config.api_key):
            self.stdout.write("4. Testing API Connectivity...")
            try:
                client = APIFootballClient()
                # Try a simple API call
                leagues_data = client.get_leagues()
                if leagues_data:
                    self.stdout.write(self.style.SUCCESS(
                        f"   ✓ API connection successful ({len(leagues_data)} leagues available)"
                    ))
                else:
                    warnings.append("API returned no data")
                    self.stdout.write(self.style.WARNING(
                        "   ⚠ API connection successful but returned no leagues"
                    ))
            except Exception as e:
                errors.append(f"API connection failed: {str(e)}")
                self.stdout.write(self.style.ERROR(
                    f"   ✗ API connection failed: {str(e)}"
                ))
            self.stdout.write("")
        
        # Summary
        self.stdout.write("="*80)
        self.stdout.write("Summary:")
        self.stdout.write("="*80)
        
        if not errors and not warnings:
            self.stdout.write(self.style.SUCCESS(
                "✓ All checks passed! Football data system is ready."
            ))
            self.stdout.write("")
            self.stdout.write("Next steps:")
            self.stdout.write("  • Ensure Celery workers are running")
            self.stdout.write("  • Configure scheduled tasks in Django admin")
            self.stdout.write("  • Monitor logs for data fetching activity")
        elif errors:
            self.stdout.write(self.style.ERROR(
                f"✗ {len(errors)} critical error(s) found:"
            ))
            for error in errors:
                self.stdout.write(self.style.ERROR(f"  • {error}"))
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Please fix the errors above before proceeding."))
        elif warnings:
            self.stdout.write(self.style.WARNING(
                f"⚠ {len(warnings)} warning(s) found:"
            ))
            for warning in warnings:
                self.stdout.write(self.style.WARNING(f"  • {warning}"))
            self.stdout.write("")
            self.stdout.write("The system may work but these issues should be addressed.")
        
        self.stdout.write("="*80)
