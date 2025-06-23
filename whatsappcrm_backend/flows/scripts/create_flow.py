# whatsappcrm_backend/flows/scripts/create_flow.py
from django.db import transaction
from flows.models import Flow, FlowStep, FlowTransition

def run():
    """
    This script is executed by 'python manage.py runscript create_flow'.
    It creates or updates the flows defined in the project.
    """
    print("Preparing to create/update flows from script...")

    with transaction.atomic():
        # --- Create/Update Get Fixtures Flow ---
        try:
            from flows.get_fixtures_flow import create_get_fixtures_flow
            flow_config = create_get_fixtures_flow()
            flow, created = Flow.objects.update_or_create(
                name=flow_config["name"],
                defaults={
                    "description": flow_config["description"],
                    "trigger_keywords": flow_config["trigger_keywords"],
                    "is_active": True
                }
            )
            if created:
                print(f'>>> Flow "{flow.name}" was created.')
            else:
                print(f'>>> Flow "{flow.name}" was updated.')
                flow.steps.all().delete() # Clear existing steps for update

            steps_map = {}
            for step_data in flow_config.get("steps", []):
                step = FlowStep.objects.create(
                    flow=flow, name=step_data["name"], step_type=step_data["step_type"],
                    is_entry_point=step_data.get("is_entry_point", False),
                    config=step_data.get("config", {})
                )
                steps_map[step.name] = step
            
            for step_data in flow_config.get("steps", []):
                current_step = steps_map[step_data["name"]]
                for trans_data in step_data.get("transitions", []):
                    next_step = steps_map.get(trans_data.get("to_step"))
                    if next_step:
                        FlowTransition.objects.create(
                            current_step=current_step,
                            next_step=next_step,
                            condition_config=trans_data.get("condition_config", {}),
                            priority=trans_data.get("priority", 0) # Add priority here
                        )
        except ImportError:
            print(">>> Skipping 'Get Fixtures Flow' creation: `create_get_fixtures_flow` not found.")
        except Exception as e:
            print(f">>> ERROR creating 'Get Fixtures Flow': {e}")


        # --- Create/Update Deposit Flow ---
        try:
            from flows.deposit_flow import create_deposit_flow
            deposit_flow_config = create_deposit_flow()
            deposit_flow, deposit_created = Flow.objects.update_or_create(
                name=deposit_flow_config["name"],
                defaults={
                    "description": deposit_flow_config["description"],
                    "trigger_keywords": deposit_flow_config["trigger_keywords"],
                    "is_active": True
                }
            )
            if deposit_created:
                print(f'>>> Flow "{deposit_flow.name}" was created.')
            else:
                print(f'>>> Flow "{deposit_flow.name}" was updated.')
                deposit_flow.steps.all().delete() # Clear existing steps for update

            deposit_steps_map = {}
            for step_data in deposit_flow_config.get("steps", []):
                step = FlowStep.objects.create(
                    flow=deposit_flow, name=step_data["name"], step_type=step_data["step_type"],
                    is_entry_point=step_data.get("is_entry_point", False),
                    config=step_data.get("config", {})
                )
                deposit_steps_map[step.name] = step
            
            for step_data in deposit_flow_config.get("steps", []):
                current_step = deposit_steps_map[step_data["name"]]
                for trans_data in step_data.get("transitions", []):
                    next_step = deposit_steps_map.get(trans_data.get("to_step"))
                    if next_step:
                        FlowTransition.objects.create(
                            current_step=current_step,
                            next_step=next_step,
                            condition_config=trans_data.get("condition_config", {}),
                            priority=trans_data.get("priority", 0) # Add priority here
                        )
        except ImportError:
            print(">>> Skipping 'Deposit Flow' creation: `create_deposit_flow` not found.")
        except Exception as e:
            print(f">>> ERROR creating 'Deposit Flow': {e}")

        # --- Create/Update User Registration Flow ---
        try:
            from flows.registration_flow import create_registration_flow
            reg_flow_config = create_registration_flow()
            reg_flow, reg_created = Flow.objects.update_or_create(
                name=reg_flow_config["name"],
                defaults={
                    "description": reg_flow_config["description"],
                    "trigger_keywords": reg_flow_config["trigger_keywords"],
                    "is_active": True
                }
            )
            if reg_created:
                print(f'>>> Flow "{reg_flow.name}" was created.')
            else:
                print(f'>>> Flow "{reg_flow.name}" was updated.')
                reg_flow.steps.all().delete() # Clear existing steps for update

            reg_steps_map = {}
            for step_data in reg_flow_config.get("steps", []):
                step = FlowStep.objects.create(
                    flow=reg_flow, name=step_data["name"], step_type=step_data["step_type"],
                    is_entry_point=step_data.get("is_entry_point", False),
                    config=step_data.get("config", {})
                )
                reg_steps_map[step.name] = step
            
            for step_data in reg_flow_config.get("steps", []):
                current_step = reg_steps_map[step_data["name"]]
                for trans_data in step_data.get("transitions", []):
                    next_step = reg_steps_map.get(trans_data.get("to_step"))
                    if next_step:
                        FlowTransition.objects.create(
                            current_step=current_step, next_step=next_step,
                            condition_config=trans_data.get("condition_config", {}),
                            priority=trans_data.get("priority", 0)
                        )
        except ImportError:
            print(">>> Skipping 'User Registration Flow' creation: `create_registration_flow` not found.")
        except Exception as e:
            print(f">>> ERROR creating 'User Registration Flow': {e}")

    print(">>> Flow creation script finished!")
