import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from flows.models import Flow, FlowStep, FlowTransition, WhatsAppFlow
from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Loads or updates predefined flow definitions from Python files in "
        "flows/definitions/ into the database.  Supports both traditional "
        "flows (Flow / FlowStep / FlowTransition) and WhatsApp UI flows "
        "(WhatsAppFlow with Meta JSON schema)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--config-id',
            type=int,
            help=(
                'MetaAppConfig ID to associate with WhatsApp UI flow records. '
                'If omitted, the first active config is used.'
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        config_id = options.get('config_id')

        # --- Resolve MetaAppConfig for WhatsApp UI flows ---
        meta_config = None
        if config_id:
            try:
                meta_config = MetaAppConfig.objects.get(pk=config_id)
            except MetaAppConfig.DoesNotExist:
                raise CommandError(f"MetaAppConfig with ID {config_id} not found.")
        else:
            meta_config = MetaAppConfig.objects.filter(is_active=True).first()

        # ----------------------------------------------------------------
        # Traditional flow definitions
        # (Flow → FlowStep → FlowTransition)
        # ----------------------------------------------------------------
        from flows.welcome_flow import create_welcome_flow
        from flows.registration_flow import create_registration_flow
        from flows.login_flow import create_login_flow
        from flows.betting_flow import create_betting_flow
        from flows.deposit_flow import create_deposit_flow
        from flows.withdrawal_flow import create_withdrawal_flow
        from flows.get_fixtures_flow import create_get_fixtures_flow
        from flows.view_results_flow import create_view_results_flow
        from flows.account_management_flow import create_account_management_flow

        traditional_flows = [
            create_welcome_flow(),
            create_registration_flow(),
            create_login_flow(),
            create_betting_flow(),
            create_deposit_flow(),
            create_withdrawal_flow(),
            create_get_fixtures_flow(),
            create_view_results_flow(),
            create_account_management_flow(),
        ]

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== Loading traditional flow definitions ==="
        ))

        for flow_def in traditional_flows:
            self._load_traditional_flow(flow_def)

        # ----------------------------------------------------------------
        # WhatsApp UI flow definitions
        # (WhatsAppFlow with Meta Flow JSON)
        # ----------------------------------------------------------------
        from flows.definitions.login_whatsapp_flow import (
            LOGIN_WHATSAPP_FLOW,
            LOGIN_WHATSAPP_FLOW_METADATA,
        )

        whatsapp_flows = [
            (LOGIN_WHATSAPP_FLOW, LOGIN_WHATSAPP_FLOW_METADATA),
        ]

        if whatsapp_flows:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n=== Loading WhatsApp UI flow definitions ==="
            ))
            if not meta_config:
                self.stderr.write(self.style.WARNING(
                    "  No active MetaAppConfig found — skipping WhatsApp UI flows. "
                    "Use --config-id to specify one."
                ))
            else:
                for flow_json, metadata in whatsapp_flows:
                    self._load_whatsapp_flow(flow_json, metadata, meta_config)

        self.stdout.write(self.style.SUCCESS(
            "\n--- ✅ All flow definitions loaded successfully ---"
        ))

    # ------------------------------------------------------------------
    # Traditional flow loader
    # ------------------------------------------------------------------
    def _load_traditional_flow(self, flow_def: dict):
        flow_name = flow_def['name']
        self.stdout.write(f"  Processing flow: '{flow_name}'...")

        is_active = flow_def.get('is_active', False)

        flow, created = Flow.objects.update_or_create(
            name=flow_name,
            defaults={
                'friendly_name': flow_def.get(
                    'friendly_name',
                    flow_name.replace('_', ' ').replace('-', ' ').title(),
                ),
                'description': flow_def.get('description', ''),
                'trigger_keywords': flow_def.get('trigger_keywords', []),
                'is_active': False,  # activate after steps are created
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"    Created new flow '{flow_name}'."))
        else:
            self.stdout.write(f"    Updating existing flow '{flow_name}'. Clearing old steps.")
            flow.steps.all().delete()

        # First pass: create all steps
        steps_map = {}
        for step_def in flow_def.get('steps', []):
            step_name = step_def['name']
            step = FlowStep.objects.create(
                flow=flow,
                name=step_name,
                step_type=step_def.get('step_type', step_def.get('type', 'send_message')),
                config=step_def.get('config', {}),
                is_entry_point=step_def.get('is_entry_point', False),
            )
            steps_map[step_name] = step

        # Second pass: create transitions
        for step_def in flow_def.get('steps', []):
            current_step = steps_map.get(step_def['name'])
            if not current_step:
                continue
            for i, trans_def in enumerate(step_def.get('transitions', [])):
                next_step = steps_map.get(trans_def.get('to_step'))
                if next_step:
                    FlowTransition.objects.create(
                        current_step=current_step,
                        next_step=next_step,
                        priority=trans_def.get('priority', i),
                        condition_config=trans_def.get('condition_config', {}),
                    )
                else:
                    self.stderr.write(self.style.WARNING(
                        f"    ⚠️  Next step '{trans_def.get('to_step')}' not found "
                        f"for transition from '{current_step.name}'. Skipping."
                    ))

        # Activate if the definition says so
        if is_active:
            flow.is_active = True
            flow.save(update_fields=['is_active'])

        self.stdout.write(self.style.SUCCESS(f"    ✅ Flow '{flow_name}' loaded."))

    # ------------------------------------------------------------------
    # WhatsApp UI flow loader
    # ------------------------------------------------------------------
    def _load_whatsapp_flow(
        self,
        flow_json: dict,
        metadata: dict,
        meta_config: MetaAppConfig,
    ):
        name = metadata['name']
        self.stdout.write(f"  Processing WhatsApp UI flow: '{name}'...")

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
            f"    ✅ {action} WhatsApp UI flow '{whatsapp_flow.friendly_name or name}'."
        ))
