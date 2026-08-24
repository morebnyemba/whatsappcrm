# football_data_app/management/commands/prune_old_fixtures.py
from django.core.management.base import BaseCommand

from football_data_app.utils import prune_old_fixtures


class Command(BaseCommand):
    help = (
        "Deletes long-finished fixtures (and their markets/odds) that nobody ever "
        "bet on, so the fixture table doesn't grow for the life of the deployment. "
        "Fixtures with ANY bet attached are never deleted, at any age -- deleting "
        "them would cascade into Bet rows and destroy settled betting history. "
        "Defaults to a dry run; pass --apply to actually delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=180,
            help='Only prune fixtures whose match_date is at least this many days in the past (default: 180).',
        )
        parser.add_argument(
            '--apply', action='store_true', default=False,
            help='Actually delete. Without this the command only reports what it would delete.',
        )
        parser.add_argument(
            '--batch-size', type=int, default=1000,
            help='Fixtures deleted per transaction (default: 1000).',
        )

    def handle(self, *args, **options):
        days = options['days']
        apply_changes = options['apply']
        batch_size = options['batch_size']

        result = prune_old_fixtures(
            older_than_days=days,
            dry_run=not apply_changes,
            batch_size=batch_size,
        )

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                f"[DRY RUN] {result['eligible']} fixture(s) older than {days} days have no bets "
                f"attached and would be deleted."
            ))
            self.stdout.write("Re-run with --apply to delete them.")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Deleted {result['deleted']} fixture(s) older than {days} days with no betting history."
            ))
        self.stdout.write(
            "Fixtures with any bet attached were left untouched (deleting them would "
            "cascade into Bet rows and destroy settled betting history)."
        )
