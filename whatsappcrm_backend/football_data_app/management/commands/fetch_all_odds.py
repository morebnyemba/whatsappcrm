# football_data_app/management/commands/fetch_all_odds.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from football_data_app.models import League, FootballFixture
from football_data_app.tasks import fetch_odds_for_event_batch_task, ODDS_FETCH_EVENT_BATCH_SIZE

class Command(BaseCommand):
    help = 'Manually triggers a task to fetch odds for all upcoming fixtures in all active leagues.'

    def handle(self, *args, **options):
        """
        The main entry point for the management command.
        """
        markets_to_fetch = "h2h,totals,spreads,btts"
        regions_to_fetch = "uk,eu,us"

        self.stdout.write(self.style.SUCCESS("Starting a full odds update for all active leagues..."))

        active_leagues = League.objects.filter(active=True)

        if not active_leagues.exists():
            self.stdout.write(self.style.WARNING("No active leagues found to update."))
            return

        total_fixtures_found = 0
        for league in active_leagues:
            event_ids = list(
                FootballFixture.objects.filter(
                    league=league,
                    status='SCHEDULED'
                ).values_list('api_id', flat=True)
            )

            if not event_ids:
                self.stdout.write(f"No scheduled fixtures found for league: {league.name}. Skipping.")
                continue

            self.stdout.write(f"Found {len(event_ids)} fixtures for {league.name}. Dispatching odds fetch tasks...")
            total_fixtures_found += len(event_ids)

            # Dispatch tasks in batches for efficiency
            for i in range(0, len(event_ids), ODDS_FETCH_EVENT_BATCH_SIZE):
                batch_ids = event_ids[i:i + ODDS_FETCH_EVENT_BATCH_SIZE]
                fetch_odds_for_event_batch_task.delay(
                    sport_key=league.api_id,
                    event_ids=batch_ids,
                    markets=markets_to_fetch,
                    regions=regions_to_fetch
                )
        
        if total_fixtures_found > 0:
            self.stdout.write(self.style.SUCCESS(f"\nAll odds update tasks have been dispatched for {total_fixtures_found} fixtures!"))
            self.stdout.write("Check your Celery worker logs and Django admin to see the new markets being created.")
        else:
            self.stdout.write(self.style.SUCCESS("\nNo scheduled fixtures found across any active leagues."))