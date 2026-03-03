import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from flows.models import WhatsAppFlow
from flows.whatsapp_flow_service import WhatsAppFlowService
from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sync WhatsApp Flows to Meta's platform for all (or specific) active "
        "MetaAppConfigs. First saves/updates flow definitions from "
        "flows/definitions/ into the database, then syncs each to Meta."
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
        parser.add_argument(
            '--skip-save',
            action='store_true',
            default=False,
            help='Skip saving definitions to DB (use only what is already there).',
        )

    def handle(self, *args, **options):
        config_id = options['config_id']
        flow_name = options['flow_name']
        publish = options['publish']
        dry_run = options['dry_run']
        skip_save = options['skip_save']

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
            self.stdout.write(f"  \u2022 {cfg.name} (phone_number_id: {cfg.phone_number_id})")

        # ------------------------------------------------------------------
        # Step 1: Save definitions from flows/definitions/ to database
        # ------------------------------------------------------------------
        if not skip_save:
            self._save_definitions_to_db(configs, dry_run)

        # ------------------------------------------------------------------
        # Step 2: Determine source flows to sync
        # ------------------------------------------------------------------
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
            self.stdout.write(f"  \u2022 {flow.name} (config: {flow.meta_app_config.name})")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No changes will be made.\n"))

        total_synced = 0
        total_published = 0
        total_errors = 0

        # Deduplicate: group source flows by their base name (ignoring config).
        # For each unique flow definition, ensure a WhatsAppFlow record exists
        # for every target config, then sync it.
        # Only use "base" definition flows as sources — derived flows (those
        # whose name already contains a phone_number_id suffix) should not
        # be re-derived for other configs.
        from flows.definitions import WHATSAPP_UI_FLOWS
        definition_names = {metadata['name'] for _, metadata in WHATSAPP_UI_FLOWS}

        seen_flow_definitions = {}
        for flow in source_flows:
            # When a specific flow name was requested, include it but still
            # apply base/derived filtering to prevent re-derivation.
            is_base = flow.name in definition_names
            is_derived = any(
                flow.name.startswith(base + '-') for base in definition_names
            )
            if is_base and flow.name not in seen_flow_definitions:
                seen_flow_definitions[flow.name] = flow
            elif not is_base and not is_derived and flow.name not in seen_flow_definitions:
                # Include non-definition, non-derived flows (manually created)
                seen_flow_definitions[flow.name] = flow

        # When a specific flow name targets a derived flow, sync it directly
        # for its own config only (don't try to derive it for other configs).
        direct_sync_flows = []
        if flow_name:
            for flow in source_flows:
                if flow.name not in seen_flow_definitions:
                    direct_sync_flows.append(flow)

        for config in configs:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n=== Config: {config.name} (phone_number_id: {config.phone_number_id}) ==="
            ))
            service = WhatsAppFlowService(config)

            for flow_name_key, source_flow in seen_flow_definitions.items():
                # If the source flow already belongs to this config, use it directly.
                if source_flow.meta_app_config_id == config.id:
                    target_flow = source_flow
                else:
                    # Look for an existing copy of this flow for the target config.
                    # Copies are named "<original_name>-<phone_number_id>".
                    derived_name = f"{source_flow.name}-{config.phone_number_id}"
                    target_flow = WhatsAppFlow.objects.filter(
                        name=derived_name,
                        meta_app_config=config,
                    ).first()

                if not target_flow:
                    derived_name = f"{source_flow.name}-{config.phone_number_id}"
                    # Create a new WhatsAppFlow record for this config
                    if dry_run:
                        self.stdout.write(
                            f"  [DRY RUN] Would create WhatsAppFlow '{derived_name}' for config '{config.name}'"
                        )
                        continue

                    target_flow = WhatsAppFlow.objects.create(
                        name=derived_name,
                        friendly_name=source_flow.friendly_name,
                        description=source_flow.description,
                        flow_json=source_flow.flow_json,
                        meta_app_config=config,
                        is_active=source_flow.is_active,
                        version=source_flow.version,
                    )
                    self.stdout.write(self.style.SUCCESS(
                        f"  \u2705 Created WhatsAppFlow '{target_flow.name}' for config '{config.name}'"
                    ))
                elif source_flow.meta_app_config_id != config.id:
                    # Refresh existing derived flow's definition from
                    # the source so stale JSON is replaced.
                    if target_flow.flow_json != source_flow.flow_json:
                        if not dry_run:
                            target_flow.flow_json = source_flow.flow_json
                            target_flow.save(update_fields=['flow_json'])
                            self.stdout.write(self.style.SUCCESS(
                                f"  \u2705 Updated flow JSON for '{target_flow.name}' from source definition"
                            ))
                        else:
                            self.stdout.write(
                                f"  [DRY RUN] Would update flow JSON for '{target_flow.name}' from source definition"
                            )

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
                        target_flow.refresh_from_db()
                        self.stdout.write(self.style.SUCCESS(
                            f"  \u2705 Synced '{target_flow.name}' (flow_id: {target_flow.flow_id})"
                        ))
                        if target_flow.sync_error:
                            self.stderr.write(self.style.WARNING(
                                f"  \u26a0\ufe0f  {target_flow.sync_error}"
                            ))
                        total_synced += 1

                        if publish:
                            pub_success = service.publish_flow(target_flow)
                            if pub_success:
                                self.stdout.write(self.style.SUCCESS(
                                    f"  \u2705 Published '{target_flow.name}'"
                                ))
                                total_published += 1
                            else:
                                target_flow.refresh_from_db()
                                self.stderr.write(self.style.ERROR(
                                    f"  \u274c Publish failed for '{target_flow.name}': {target_flow.sync_error}"
                                ))
                                total_errors += 1
                    else:
                        target_flow.refresh_from_db()
                        self.stderr.write(self.style.ERROR(
                            f"  \u274c Sync failed for '{target_flow.name}': {target_flow.sync_error}"
                        ))
                        total_errors += 1
                except Exception as e:
                    self.stderr.write(self.style.ERROR(
                        f"  \u274c Error syncing '{target_flow.name}': {e}"
                    ))
                    logger.error(f"Error syncing flow '{target_flow.name}': {e}", exc_info=True)
                    total_errors += 1

            # Sync derived flows directly for their own config (no re-derivation)
            for direct_flow in direct_sync_flows:
                if direct_flow.meta_app_config_id != config.id:
                    continue

                if dry_run:
                    self.stdout.write(f"  [DRY RUN] Would sync flow '{direct_flow.name}'")
                    if publish:
                        self.stdout.write(f"  [DRY RUN] Would publish flow '{direct_flow.name}'")
                    continue

                self.stdout.write(f"  Syncing '{direct_flow.name}'...")
                try:
                    success = service.sync_flow(direct_flow)
                    if success:
                        direct_flow.refresh_from_db()
                        self.stdout.write(self.style.SUCCESS(
                            f"  \u2705 Synced '{direct_flow.name}' (flow_id: {direct_flow.flow_id})"
                        ))
                        if direct_flow.sync_error:
                            self.stderr.write(self.style.WARNING(
                                f"  \u26a0\ufe0f  {direct_flow.sync_error}"
                            ))
                        total_synced += 1

                        if publish:
                            pub_success = service.publish_flow(direct_flow)
                            if pub_success:
                                self.stdout.write(self.style.SUCCESS(
                                    f"  \u2705 Published '{direct_flow.name}'"
                                ))
                                total_published += 1
                            else:
                                direct_flow.refresh_from_db()
                                self.stderr.write(self.style.ERROR(
                                    f"  \u274c Publish failed for '{direct_flow.name}': {direct_flow.sync_error}"
                                ))
                                total_errors += 1
                    else:
                        direct_flow.refresh_from_db()
                        self.stderr.write(self.style.ERROR(
                            f"  \u274c Sync failed for '{direct_flow.name}': {direct_flow.sync_error}"
                        ))
                        total_errors += 1
                except Exception as e:
                    self.stderr.write(self.style.ERROR(
                        f"  \u274c Error syncing '{direct_flow.name}': {e}"
                    ))
                    logger.error(f"Error syncing flow '{direct_flow.name}': {e}", exc_info=True)
                    total_errors += 1

        # Summary
        self.stdout.write(self.style.SUCCESS(
            f"\n--- Summary ---\n"
            f"  Synced:    {total_synced}\n"
            f"  Published: {total_published}\n"
            f"  Errors:    {total_errors}"
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("  (Dry run \u2014 no actual changes were made)"))
        self.stdout.write(self.style.SUCCESS("--- Done ---"))

    def _save_definitions_to_db(self, configs, dry_run):
        """
        Save WhatsApp UI flow definitions from flows/definitions/ into the
        database for the first available config.  This ensures the DB always
        has the latest definitions before syncing to Meta.
        """
        from flows.definitions import WHATSAPP_UI_FLOWS

        if not WHATSAPP_UI_FLOWS:
            return

        meta_config = configs[0]  # use first config for initial save

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== Saving WhatsApp UI flow definitions to database ==="
        ))

        for flow_json, metadata in WHATSAPP_UI_FLOWS:
            name = metadata['name']
            if dry_run:
                self.stdout.write(f"  [DRY RUN] Would save '{name}' to database")
                continue

            with transaction.atomic():
                whatsapp_flow, created = WhatsAppFlow.objects.update_or_create(
                    name=name,
                    defaults={
                        'friendly_name': metadata.get('friendly_name', name),
                        'description': metadata.get('description', ''),
                        'flow_json': flow_json,
                        'is_active': metadata.get('is_active', False),
                        'meta_app_config': meta_config,
                    },
                )
            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(
                f"  \u2705 {action} '{whatsapp_flow.friendly_name or name}' in database"
            ))
