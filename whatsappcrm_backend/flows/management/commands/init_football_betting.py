from django.core.management.base import BaseCommand
from flows.football_betting_flow import initialize_football_betting_flow

class Command(BaseCommand):
    help = 'Initialize the football betting flow'

    def handle(self, *args, **options):
        try:
            flow = initialize_football_betting_flow()
            self.stdout.write(
                self.style.SUCCESS(f'Successfully initialized football betting flow: {flow.name}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to initialize football betting flow: {str(e)}')
            ) 