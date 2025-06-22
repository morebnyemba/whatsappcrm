from django.core.management.base import BaseCommand
from django.db import transaction
from flows.models import Flow, FlowStep, FlowTransition
from flows.registration_flow import create_registration_flow
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Creates or updates the User Registration flow in the database.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("--- Starting User Registration Flow Creation Script ---"))

        with transaction.atomic():
            flow_config = create_registration_flow()

            # Get or create the Flow
            flow, created = Flow.objects.update_or_create(
                name=flow_config["name"],
                defaults={
                    "description": flow_config["description"],
                    "trigger_keywords": flow_config["trigger_keywords"],
                    "is_active": flow_config.get("is_active", True)
                }
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Flow "{flow.name}" was created.'))
            else:
                self.stdout.write(self.style.WARNING(f'🔄 Flow "{flow.name}" was found, updating it.'))
                # Clear existing steps and transitions to ensure a clean slate
                flow.steps.all().delete()
                self.stdout.write(self.style.WARNING(f'🗑️  Cleared all old steps and transitions for "{flow.name}".'))

            # Create steps
            steps_map = {}
            for step_data in flow_config.get("steps", []):
                self.stdout.write(f'  -> Creating step: {step_data["name"]}')
                step = FlowStep.objects.create(
                    flow=flow,
                    name=step_data["name"],
                    step_type=step_data["step_type"],
                    is_entry_point=step_data.get("is_entry_point", False),
                    config=step_data.get("config", {})
                )
                steps_map[step.name] = step

            # Create transitions
            for step_data in flow_config.get("steps", []):
                current_step = steps_map.get(step_data["name"])
                if not current_step:
                    logger.error(f"Step '{step_data['name']}' not found in steps_map. Skipping transitions for this step.")
                    continue

                for i, trans_data in enumerate(step_data.get("transitions", [])):
                    next_step = steps_map.get(trans_data.get("to_step"))
                    if next_step:
                        self.stdout.write(f'    -> Creating transition from "{current_step.name}" to "{next_step.name}"')
                        FlowTransition.objects.create(
                            current_step=current_step, next_step=next_step,
                            priority=trans_data.get("priority", i + 1),
                            condition_config=trans_data.get("condition_config", {})
                        )
                    else:
                        logger.warning(f"Next step '{trans_data.get('to_step')}' not found for transition from '{current_step.name}'. Skipping this transition.")

        self.stdout.write(self.style.SUCCESS("\n--- ✅ User Registration Flow Creation Script Finished Successfully! ---"))
        self.stdout.write(self.style.SUCCESS("You can now run this command using: python manage.py create_reg_flow"))