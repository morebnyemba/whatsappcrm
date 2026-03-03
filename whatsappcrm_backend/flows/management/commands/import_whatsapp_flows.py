import logging

from django.core.management.base import BaseCommand

from flows.whatsapp_flow_service import WhatsAppFlowService
from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Import WhatsApp UI Flow definitions from Meta's platform into the "
        "local database.  For every flow found on Meta, the command downloads "
        "its JSON asset and creates (or updates) a local WhatsAppFlow record."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--config-id',
            type=int,
            help='Import flows only for this MetaAppConfig ID. If omitted, all active configs are used.',
        )

    def handle(self, *args, **options):
        config_id = options['config_id']

        # Determine target configs
        if config_id:
            try:
                configs = [MetaAppConfig.objects.get(pk=config_id)]
            except MetaAppConfig.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"MetaAppConfig with ID {config_id} not found."))
                return
        else:
            configs = list(MetaAppConfig.objects.get_all_active_configs())
            if not configs:
                self.stderr.write(self.style.ERROR("No active MetaAppConfigs found."))
                return

        self.stdout.write(self.style.SUCCESS(
            f"--- Importing WhatsApp Flows from Meta for {len(configs)} config(s) ---"
        ))

        total_imported = 0
        total_updated = 0
        total_errors = 0

        for config in configs:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n=== Config: {config.name} (phone_number_id: {config.phone_number_id}) ==="
            ))

            try:
                service = WhatsAppFlowService(config)
                results = service.import_flows_from_meta()

                for detail in results.get('details', []):
                    action = detail.get('action')
                    name = detail.get('name', 'Unknown')
                    fid = detail.get('flow_id', 'N/A')
                    if action == 'imported':
                        self.stdout.write(self.style.SUCCESS(
                            f"  \u2705 Imported '{name}' (flow_id: {fid})"
                        ))
                    elif action == 'updated':
                        self.stdout.write(self.style.SUCCESS(
                            f"  \u2705 Updated '{name}' (flow_id: {fid})"
                        ))
                    elif action == 'error':
                        self.stderr.write(self.style.ERROR(
                            f"  \u274c Error for '{name}' (flow_id: {fid}): {detail.get('error')}"
                        ))

                total_imported += results.get('imported', 0)
                total_updated += results.get('updated', 0)
                total_errors += results.get('errors', 0)

            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f"  \u274c Error importing from config '{config.name}': {e}"
                ))
                logger.error(f"Error importing flows for config '{config.name}': {e}", exc_info=True)
                total_errors += 1

        # Summary
        self.stdout.write(self.style.SUCCESS(
            f"\n--- Summary ---\n"
            f"  Imported: {total_imported}\n"
            f"  Updated:  {total_updated}\n"
            f"  Errors:   {total_errors}"
        ))
        self.stdout.write(self.style.SUCCESS("--- Done ---"))
