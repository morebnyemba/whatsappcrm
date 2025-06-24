def create_the_flow():
    from django.db import transaction
    from flows.models import Flow, FlowStep, FlowTransition
    from flows.deposit_flow import create_deposit_flow # Import the new deposit flow
    from flows.withdrawal_flow import create_withdrawal_flow # Import the new withdrawal flow
    
    print("Preparing to create the flow from a script...")
    
    with transaction.atomic():

        # Create/Update Deposit Flow
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
                        current_step=current_step, next_step=next_step,
                        condition_config=trans_data.get("condition_config", {}),
                        priority=trans_data.get("priority", 0) # Add this line
                    )

        # Create/Update Withdrawal Flow
        withdrawal_flow_config = create_withdrawal_flow()
        withdrawal_flow, withdrawal_created = Flow.objects.update_or_create(
            name=withdrawal_flow_config["name"],
            defaults={
                "description": withdrawal_flow_config["description"],
                "trigger_keywords": withdrawal_flow_config["trigger_keywords"],
                "is_active": True
            }
        )
        if withdrawal_created:
            print(f'>>> Flow "{withdrawal_flow.name}" was created.')
        else:
            print(f'>>> Flow "{withdrawal_flow.name}" was updated.')
            withdrawal_flow.steps.all().delete() # Clear existing steps for update

        withdrawal_steps_map = {}
        for step_data in withdrawal_flow_config.get("steps", []):
            step = FlowStep.objects.create(
                flow=withdrawal_flow, name=step_data["name"], step_type=step_data["step_type"],
                is_entry_point=step_data.get("is_entry_point", False),
                config=step_data.get("config", {})
            )
            withdrawal_steps_map[step.name] = step
        
        for step_data in withdrawal_flow_config.get("steps", []):
            current_step = withdrawal_steps_map[step_data["name"]]
            for trans_data in step_data.get("transitions", []):
                next_step = withdrawal_steps_map.get(trans_data.get("to_step"))
                if next_step:
                    FlowTransition.objects.create(
                        current_step=current_step, next_step=next_step,
                        condition_config=trans_data.get("condition_config", {}),
                        priority=trans_data.get("priority", 0)
                    )
    print(">>> Flow creation script finished!")

create_the_flow()
