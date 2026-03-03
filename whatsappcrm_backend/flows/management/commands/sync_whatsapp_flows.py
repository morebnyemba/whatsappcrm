import logging

from django.core.management.base import BaseCommand

from flows.models import WhatsAppFlow
from flows.whatsapp_flow_service import WhatsAppFlowService
from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sync WhatsApp Flows to Meta's platform for all (or specific) active "
        "MetaAppConfigs. For every WhatsAppFlow in the database, an equivalent "
        "WhatsAppFlow record is ensured for each target config and then synced."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--config-id',
            type=int,
            help='Sync flows only for this MetaAppConfig ID. If omitted, all active configs are used.',
        )
        parser.add_argument(
            '--flow-name',
            type=str,
            help='Sync only the WhatsAppFlow with this name. If omitted, all flows are synced.',
        )
        parser.add_argument(
            '--publish',
            action='store_true',
            default=False,
            help='Also publish flows after syncing.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Show what would happen without making changes.',
        )

    def handle(self, *args, **options):
        config_id = options['config_id']
        flow_name = options['flow_name']
        publish = options['publish']
        dry_run = options['dry_run']

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
            f"--- Syncing WhatsApp Flows to {len(configs)} config(s) ---"
        ))
        for cfg in configs:
            self.stdout.write(f"  • {cfg.name} (phone_number_id: {cfg.phone_number_id})")

        # Determine source flows
        if flow_name:
            source_flows = list(WhatsAppFlow.objects.filter(name=flow_name))
            if not source_flows:
                self.stderr.write(self.style.ERROR(f"No WhatsAppFlow with name '{flow_name}' found."))
                return
        else:
            source_flows = list(WhatsAppFlow.objects.all())
            if not source_flows:
                self.stderr.write(self.style.WARNING("No WhatsAppFlow records in the database. Nothing to sync."))
                return

        self.stdout.write(f"\nFlows to sync ({len(source_flows)}):")
        for flow in source_flows:
            self.stdout.write(f"  • {flow.name} (config: {flow.meta_app_config.name})")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No changes will be made.\n"))

        total_synced = 0
        total_published = 0
        total_errors = 0

        # Deduplicate: group source flows by their base name (ignoring config).
        # For each unique flow definition, ensure a WhatsAppFlow record exists
        # for every target config, then sync it.
        seen_flow_definitions = {}
        for flow in source_flows:
            if flow.name not in seen_flow_definitions:
                seen_flow_definitions[flow.name] = flow

        for config in configs:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n=== Config: {config.name} (phone_number_id: {config.phone_number_id}) ==="
            ))
            service = WhatsAppFlowService(config)

            for flow_name_key, source_flow in seen_flow_definitions.items():
                # Check if a WhatsAppFlow already exists for this config
                target_flow = WhatsAppFlow.objects.filter(
                    name=source_flow.name,
                    meta_app_config=config,
                ).first()

                if not target_flow and source_flow.meta_app_config_id == config.id:
                    target_flow = source_flow

                if not target_flow:
                    # Create a new WhatsAppFlow record for this config
                    if dry_run:
                        self.stdout.write(
                            f"  [DRY RUN] Would create WhatsAppFlow '{source_flow.name}' for config '{config.name}'"
                        )
                        continue

                    target_flow = WhatsAppFlow.objects.create(
                        name=f"{source_flow.name}__{config.phone_number_id}",
                        friendly_name=source_flow.friendly_name,
                        description=source_flow.description,
                        flow_json=source_flow.flow_json,
                        meta_app_config=config,
                        is_active=source_flow.is_active,
                        version=source_flow.version,
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✅ Created WhatsAppFlow '{target_flow.name}' for config '{config.name}'"
                    ))

                if dry_run:
                    self.stdout.write(f"  [DRY RUN] Would sync flow '{target_flow.name}'")
                    if publish:
                        self.stdout.write(f"  [DRY RUN] Would publish flow '{target_flow.name}'")
                    continue

                # Sync the flow
                self.stdout.write(f"  Syncing '{target_flow.name}'...")
                try:
                    success = service.sync_flow(target_flow)
                    if success:
                        self.stdout.write(self.style.SUCCESS(
                            f"  ✅ Synced '{target_flow.name}' (flow_id: {target_flow.flow_id})"
                        ))
                        total_synced += 1

                        if publish:
                            pub_success = service.publish_flow(target_flow)
                            if pub_success:
                                self.stdout.write(self.style.SUCCESS(
                                    f"  ✅ Published '{target_flow.name}'"
                                ))
                                total_published += 1
                            else:
                                self.stderr.write(self.style.ERROR(
                                    f"  ❌ Publish failed for '{target_flow.name}': {target_flow.sync_error}"
                                ))
                                total_errors += 1
                    else:
                        self.stderr.write(self.style.ERROR(
                            f"  ❌ Sync failed for '{target_flow.name}': {target_flow.sync_error}"
                        ))
                        total_errors += 1
                except Exception as e:
                    self.stderr.write(self.style.ERROR(
                        f"  ❌ Error syncing '{target_flow.name}': {e}"
                    ))
                    logger.error(f"Error syncing flow '{target_flow.name}': {e}", exc_info=True)
                    total_errors += 1

        # Summary
        self.stdout.write(self.style.SUCCESS(
            f"\n--- Summary ---\n"
            f"  Synced:    {total_synced}\n"
            f"  Published: {total_published}\n"
            f"  Errors:    {total_errors}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("  (Dry run — no actual changes were made)"))
        self.stdout.write(self.style.SUCCESS("--- Done ---"))
