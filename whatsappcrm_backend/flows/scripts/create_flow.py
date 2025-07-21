# whatsappcrm_backend/flows/scripts/create_flow.py
from django.db import transaction
from flows.models import Flow, FlowStep, FlowTransition
import importlib

def _create_or_update_flow_from_config(flow_creator_func):
    """Helper function to create or update a single flow from its config."""
    flow_config = flow_creator_func()
    flow_name = flow_config["name"]
    
    print(f'>>> Starting creation/update for {flow_name}...')
    
    flow, created = Flow.objects.update_or_create(
        name=flow_name,
        defaults={
            "description": flow_config["description"],
            "trigger_keywords": flow_config["trigger_keywords"],
            "is_active": True
        }
    )
    if created:
        print(f'>>> Flow "{flow_name}" was created.')
    else:
        print(f'>>> Flow "{flow_name}" was updated.')
        flow.steps.all().delete()  # Clear existing steps for update

    steps_map = {}
    for step_data in flow_config.get("steps", []):
        try:
            step = FlowStep.objects.create(
                flow=flow, name=step_data["name"], step_type=step_data["step_type"],
                is_entry_point=step_data.get("is_entry_point", False),
                config=step_data.get("config", {})
            )
            steps_map[step.name] = step
            print(f'    Created step: {step.name}')
        except Exception as e:
            print(f'    ERROR creating step "{step_data["name"]}" for "{flow_name}": {e}')
            raise

    for step_data in flow_config.get("steps", []):
        current_step = steps_map[step_data["name"]]
        for trans_data in step_data.get("transitions", []):
            next_step = steps_map.get(trans_data.get("to_step"))
            if next_step:
                try:
                    FlowTransition.objects.create(
                        current_step=current_step,
                        next_step=next_step,
                        condition_config=trans_data.get("condition_config", {}),
                        priority=trans_data.get("priority", 0)
                    )
                    print(f'        Created transition: {current_step.name} -> {next_step.name}')
                except Exception as e:
                    print(f'        ERROR creating transition from "{current_step.name}" to "{trans_data.get("to_step")}" for "{flow_name}": {e}')
                    raise
    print(f'>>> {flow_name} steps and transitions processed.')


def run():
    """
    This script is executed by 'python manage.py runscript create_flow'.
    It creates or updates all defined flows in the project.
    """
    print("Preparing to create/update flows from script...")

    # List of flow modules and their creator function names
    flow_definitions = [
        ('flows.welcome_flow', 'create_welcome_flow'),
        ('flows.account_management_flow', 'create_account_management_flow'),
        ('flows.get_fixtures_flow', 'create_get_fixtures_flow'),
        ('flows.view_results_flow', 'create_view_results_flow'),
        ('flows.deposit_flow', 'create_deposit_flow'),
        ('flows.registration_flow', 'create_registration_flow'),
        ('flows.withdrawal_flow', 'create_withdrawal_flow'),
        ('flows.betting_flow', 'create_betting_flow'),
        ('referrals.flows', 'create_referral_flow'), # Add the referral flow
    ]

    with transaction.atomic():
        for module_path, func_name in flow_definitions:
            try:
                module = importlib.import_module(module_path)
                flow_creator_func = getattr(module, func_name)
                _create_or_update_flow_from_config(flow_creator_func)
            except ImportError:
                print(f">>> Skipping '{func_name}' creation: module '{module_path}' not found.")
            except AttributeError:
                print(f">>> Skipping '{func_name}' creation: function not found in '{module_path}'.")
            except Exception as e:
                print(f">>> ERROR creating flow from '{module_path}.{func_name}': {e}")
                # Re-raise to ensure the transaction is rolled back
                raise

    print(">>> Flow creation script finished!")
