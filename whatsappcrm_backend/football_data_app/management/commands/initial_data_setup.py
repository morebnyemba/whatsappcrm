# football_data_app/management/commands/initial_data_setup.py
from django.core.management.base import BaseCommand
from football_data_app.tasks_api_football_v3 import run_api_football_v3_full_update_task


class Command(BaseCommand):
    help = (
        'Dispatches the full initial data setup pipeline (API-Football v3): '
        'fetches leagues, then events, then odds, as a single chained Celery pipeline.'
    )

    def handle(self, *args, **options):
        result = run_api_football_v3_full_update_task.delay()

        self.stdout.write(self.style.SUCCESS(
            f">>> Dispatched run_api_football_v3_full_update_task (task id: {result.id})."
        ))
        self.stdout.write(">>> Monitor the celery_cpu_worker logs for progress.")
        self.stdout.write(">>> It may take several minutes for all odds for all leagues to be fetched.")
