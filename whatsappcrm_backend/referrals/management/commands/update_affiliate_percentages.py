from decimal import Decimal

from django.core.management.base import BaseCommand

from referrals.models import ReferralSettings

# This project's migrations aren't committed to git (see .gitignore) — they're
# regenerated fresh on each deploy via `makemigrations`, which only detects
# SCHEMA changes, never data fixes. So bumping an already-deployed
# ReferralSettings row from its old default onto the new one needs a
# management command, not a data migration.
OLD_AGENT_COMMISSION_DEFAULT = Decimal('0.0500')
NEW_DEFAULT = Decimal('0.2500')


class Command(BaseCommand):
    help = (
        "Bumps ReferralSettings.agent_commission_percentage from the old 5% "
        "default to the current 25% default, if it's still sitting at the old "
        "value (i.e. an admin never customised it). Safe to re-run — a no-op "
        "once applied, or if the value has already been customised."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='Set agent_commission_percentage to 25% regardless of its current value.',
        )

    def handle(self, *args, **options):
        settings = ReferralSettings.load()
        current = settings.agent_commission_percentage

        if options['force']:
            settings.agent_commission_percentage = NEW_DEFAULT
            settings.save(update_fields=['agent_commission_percentage'])
            self.stdout.write(self.style.SUCCESS(
                f"agent_commission_percentage forced to {NEW_DEFAULT:.2%} (was {current:.2%})."
            ))
            return

        if current == OLD_AGENT_COMMISSION_DEFAULT:
            settings.agent_commission_percentage = NEW_DEFAULT
            settings.save(update_fields=['agent_commission_percentage'])
            self.stdout.write(self.style.SUCCESS(
                f"agent_commission_percentage updated: {OLD_AGENT_COMMISSION_DEFAULT:.2%} -> {NEW_DEFAULT:.2%}."
            ))
        else:
            self.stdout.write(
                f"agent_commission_percentage is already {current:.2%} (not the old {OLD_AGENT_COMMISSION_DEFAULT:.2%} "
                f"default) — leaving it as-is. Use --force to set it to {NEW_DEFAULT:.2%} anyway."
            )

        self.stdout.write(
            "\nReminder: bonus_percentage_each and agent_win_deduction_percentage "
            "both already default to 25% for any newly-created settings row, but "
            "won't retroactively change an existing custom value either — check "
            "them in the Django admin (Referrals > Agent Program Settings) if unsure."
        )
