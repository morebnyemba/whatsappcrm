# football_data_app/management/commands/initial_data_setup.py
import time
from django.core.management.base import BaseCommand
from football_data_app.tasks import fetch_and_update_leagues_task, process_leagues_task

class Command(BaseCommand):
    help = 'Runs the full initial data setup pipeline: fetches leagues, then events, then odds.'

    def handle(self, *args, **options):
        """
        This command dispatches the main Celery tasks in a sequence to ensure
        the database is populated correctly.
        """
        self.stdout.write(self.style.SUCCESS(">>> Step 1: Dispatching task to fetch all leagues..."))
        
        # Dispatch the first task to fetch and create all leagues
        league_task_result = fetch_and_update_leagues_task.apply_async()
        
        # We wait for the league task to complete before proceeding.
        self.stdout.write(">>> Waiting 30 seconds for leagues to be created in the database...")
        time.sleep(30)
        
        self.stdout.write(self.style.SUCCESS("\n>>> Step 2: Dispatching task to process leagues (this will fetch events and odds)..."))
        
        # Now that leagues exist, dispatch the main processing task
        # This task will find the leagues and create sub-tasks for events and odds.
        process_leagues_task.delay()

        self.stdout.write(self.style.SUCCESS("\n>>> All initial setup tasks have been dispatched."))
        self.stdout.write(self.style.SUCCESS(">>> Monitor your Celery worker logs for progress."))
        self.stdout.write(">>> It may take several minutes for all odds for all leagues to be fetched.")