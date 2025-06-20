def create_the_flow():
    from django.db import transaction
    from flows.models import Flow, FlowStep, FlowTransition
    from flows.get_fixtures_flow import create_get_fixtures_flow
    
    print("Preparing to create the flow from a script...")
    
    with transaction.atomic():
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
            flow.steps.all().delete()

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
                        current_step=current_step, next_step=next_step,
                        condition_config=trans_data.get("condition_config", {})
                    )
    print(">>> Flow creation script finished!")

create_the_flow()

