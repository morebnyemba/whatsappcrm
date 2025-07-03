from django.core.management.base import BaseCommand, CommandError
from football_data_app.models import FootballFixture
from football_data_app.tasks import settle_fixture_pipeline_task

class Command(BaseCommand):
    """
    A Django management command to manually trigger the settlement pipeline for a specific fixture.

    This is useful for re-running settlement on a fixture that may have failed
    or for manually settling a fixture for testing purposes.

    Usage:
        python manage.py settle_fixture <fixture_id>
        python manage.py settle_fixture <fixture_id> --force
    """
    help = 'Manually triggers the settlement pipeline for a specific finished fixture.'

    def add_arguments(self, parser):
        """Adds command-line arguments to the command."""
        parser.add_argument('fixture_id', type=int, help='The ID of the FootballFixture to settle.')
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force settlement even if the fixture is not marked as FINISHED. This will mark the fixture as FINISHED.',
        )

    def handle(self, *args, **options):
        """The actual logic of the command."""
        fixture_id = options['fixture_id']
        force_settle = options['force']

        try:
            fixture = FootballFixture.objects.get(id=fixture_id)
        except FootballFixture.DoesNotExist:
            raise CommandError(f'Fixture with ID "{fixture_id}" does not exist.')

        self.stdout.write(f"Found fixture: {fixture}")

        if fixture.status != FootballFixture.FixtureStatus.FINISHED:
            if force_settle:
                self.stdout.write(self.style.WARNING(f"Fixture {fixture_id} is not marked as FINISHED (current status: {fixture.status}). Forcing status to FINISHED."))
                if fixture.home_team_score is None or fixture.away_team_score is None:
                    self.stdout.write(self.style.WARNING("Fixture scores are not set. Assuming 0-0 for settlement."))
                    fixture.home_team_score = 0
                    fixture.away_team_score = 0
                fixture.status = FootballFixture.FixtureStatus.FINISHED
                fixture.save(update_fields=['status', 'home_team_score', 'away_team_score'])
            else:
                raise CommandError(f'Fixture {fixture_id} is not marked as FINISHED (current status: {fixture.status}). Use --force to settle it anyway.')

        self.stdout.write(f"Dispatching settlement pipeline for fixture ID: {fixture_id}...")
        settle_fixture_pipeline_task.delay(fixture_id)
        self.stdout.write(self.style.SUCCESS(f'Successfully dispatched settlement pipeline for fixture ID {fixture_id}. Check Celery logs for progress.'))