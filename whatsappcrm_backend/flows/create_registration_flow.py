import os
import django

# --- Django Setup ---
# This allows the script to be run from the command line.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings') # Assuming WORKDIR is the project root
django.setup()
# --- End Django Setup ---

from django.db import transaction
from flows.models import Flow, FlowStep, FlowTransition
from flows.registration_flow import create_registration_flow

def run():
    """
    Creates or updates the User Registration flow in the database from its definition.
    This script is idempotent. Running it again will update the existing flow.
    """
    print("--- Starting User Registration Flow Creation Script ---")

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
            print(f'✅ Flow "{flow.name}" was created.')
        else:
            print(f'🔄 Flow "{flow.name}" was found, updating it.')
            # Clear existing steps and transitions to ensure a clean slate
            flow.steps.all().delete()
            print(f'🗑️  Cleared all old steps and transitions for "{flow.name}".')

        # Create steps
        steps_map = {}
        for step_data in flow_config.get("steps", []):
            print(f'  -> Creating step: {step_data["name"]}')
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
            for i, trans_data in enumerate(step_data.get("transitions", [])):
                next_step = steps_map.get(trans_data.get("to_step"))
                if next_step:
                    print(f'    -> Creating transition from "{current_step.name}" to "{next_step.name}"')
                    FlowTransition.objects.create(
                        current_step=current_step, next_step=next_step,
                        priority=trans_data.get("priority", i + 1),
                        condition_config=trans_data.get("condition_config", {})
                    )

    print("\n--- ✅ User Registration Flow Creation Script Finished Successfully! ---")
    print("To run this script, navigate to your backend root directory and execute:")
    print("python create_registration_flow.py")

if __name__ == "__main__":
    run()