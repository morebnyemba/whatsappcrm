# whatsappcrm_backend/flows/serializers.py

from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Flow, FlowStep, FlowTransition, ContactFlowState, WhatsAppFlow, WhatsAppFlowResponse

import logging
logger = logging.getLogger(__name__)

class FlowTransitionSerializer(serializers.ModelSerializer):
    """
    Serializer for FlowTransition.
    Handles creation, update, and retrieval of flow transitions.
    """
    current_step_name = serializers.CharField(source='current_step.name', read_only=True)
    next_step_name = serializers.CharField(source='next_step.name', read_only=True)

    current_step = serializers.PrimaryKeyRelatedField(queryset=FlowStep.objects.all())
    next_step = serializers.PrimaryKeyRelatedField(queryset=FlowStep.objects.all())
    condition_config = serializers.JSONField(required=False, allow_null=True, default=dict)

    class Meta:
        model = FlowTransition
        fields = [
            'id',
            'current_step',
            'current_step_name',
            'next_step',
            'next_step_name',
            'condition_config',
            'priority'
        ]
        read_only_fields = ('id', 'current_step_name', 'next_step_name')

    def validate_condition_config(self, value): # Validates the 'condition_config' field
        if value is None:
            return {} # Default to empty dict if allow_null=True and None is passed
        if not isinstance(value, dict):
            raise serializers.ValidationError("Condition config must be a JSON object (dictionary).")
        
        condition_type = value.get('type')
        if 'type' in value and (not isinstance(condition_type, str) or not condition_type.strip()):
            # Corrected: Raise with a simple string for the field-level validator
            raise serializers.ValidationError("Condition 'type' must be a non-empty string if provided.")
        
        # Example: Add more specific validation based on known condition_types
        # if condition_type == 'user_reply_matches_keyword':
        #     if not value.get('keyword'):
        #         raise serializers.ValidationError("A 'keyword' is required for 'user_reply_matches_keyword' conditions.")
        #     if 'case_sensitive' not in value or not isinstance(value.get('case_sensitive'), bool):
        #         raise serializers.ValidationError("'case_sensitive' (boolean) is required for keyword conditions.")
        return value

    def validate(self, data): # Object-level validation
        # 'current_step' and 'next_step' in 'data' will be resolved FlowStep instances here
        # because they are PrimaryKeyRelatedFields and validation has passed for them individually.
        current_step = data.get('current_step', getattr(self.instance, 'current_step', None))
        next_step = data.get('next_step', getattr(self.instance, 'next_step', None))

        if current_step and next_step:
            if current_step.flow_id != next_step.flow_id:
                # This is a non-field error or an error related to multiple fields.
                # Raising it this way makes it a non_field_error.
                # To target a specific field: {"field_name": ["message"]}
                raise serializers.ValidationError(
                    "Current step and next step must belong to the same flow."
                )
            # Optional: disallow direct self-transitions unless specifically designed
            # if current_step.pk == next_step.pk:
            #     raise serializers.ValidationError(
            #         {"next_step": "A step cannot transition directly to itself without a specific condition allowing loops."}
            #     )
        elif not current_step and 'current_step' in data: # current_step was provided but resolved to None (e.g. invalid PK)
             pass # Let PrimaryKeyRelatedField's default validation handle "does not exist"
        elif not next_step and 'next_step' in data:
             pass # Let PrimaryKeyRelatedField's default validation handle "does not exist"

        return data


class FlowStepSerializer(serializers.ModelSerializer):
    """
    Serializer for FlowStep.
    Includes nested outgoing transitions for read-only display.
    """
    flow_name = serializers.CharField(source='flow.name', read_only=True)
    step_type_display = serializers.CharField(source='get_step_type_display', read_only=True)
    outgoing_transitions = FlowTransitionSerializer(many=True, read_only=True) # Read-only display

    flow = serializers.PrimaryKeyRelatedField(queryset=Flow.objects.all())
    config = serializers.JSONField(required=False, allow_null=True, default=dict)

    class Meta:
        model = FlowStep
        fields = [
            'id', 'flow', 'flow_name', 'name', 'step_type',
            'step_type_display', 'config', 'is_entry_point',
            'outgoing_transitions', 'created_at', 'updated_at'
        ]
        read_only_fields = (
            'id', 'flow_name', 'step_type_display',
            'outgoing_transitions', 'created_at', 'updated_at'
        )

    def validate_config(self, value): # Validates the 'config' field
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Config must be a JSON object (dictionary).")

        # Determine step_type from the initial data submitted or from the instance if updating
        step_type = self.initial_data.get('step_type', getattr(self.instance, 'step_type', None))

        if not step_type:
            # This situation should ideally be prevented by step_type being a required field.
            # If step_type is not present, we cannot perform type-specific config validation.
            # Depending on requirements, either return value or raise an error.
            # If config content *depends* on step_type, an error is more appropriate.
            if value: # If config is not empty but step_type is unknown
                 logger.warning("Config provided for FlowStep but step_type is unknown/missing. Cannot perform type-specific validation.")
            return value 

        if step_type == 'send_message':
            # services.py (as per message #49) expects config like:
            # {"message_type": "text", "text": {"body": "..."}}
            if not value.get('message_type'):
                # Corrected: This error is for the 'config' field.
                raise serializers.ValidationError(
                    "For 'send_message' steps, the config must include a 'message_type' key."
                )
            # Add further checks, e.g., if message_type is 'text', then 'text' key with 'body' should exist
            # msg_type_val = value.get('message_type')
            # if msg_type_val == 'text' and (not isinstance(value.get('text'), dict) or 'body' not in value.get('text')):
            #     raise serializers.ValidationError("For text messages, config.text.body is required.")

        elif step_type == 'question':
            # services.py expects config like:
            # {"message_config": {...}, "reply_config": {...}}
            if 'message_config' not in value or not isinstance(value.get('message_config'), dict):
                raise serializers.ValidationError(
                    "For 'question' steps, config must include a 'message_config' object."
                )
            if 'reply_config' not in value or not isinstance(value.get('reply_config'), dict):
                raise serializers.ValidationError(
                    "For 'question' steps, config must include a 'reply_config' object."
                )
        elif step_type == 'action':
            # services.py expects config like:
            # {"actions_to_run": [...]}
            actions_to_run = value.get('actions_to_run')
            if not isinstance(actions_to_run, list):
                raise serializers.ValidationError(
                    "For 'action' steps, config must include 'actions_to_run' as a list."
                )
        # Add more step_type specific config validations as your system evolves
        return value

    def validate_is_entry_point(self, value): # Validates the 'is_entry_point' field
        if value is True: # Only perform check if trying to set it to True
            flow_instance = None
            # When creating a new step, 'flow' is in self.initial_data (as a PK)
            # When updating a step, 'flow' might or might not be in self.initial_data.
            # If 'flow' is being changed, self.initial_data['flow'] has the new PK.
            # If 'flow' is not being changed, use self.instance.flow.

            # `self.context['request'].data` could also be used for more raw access if needed.
            # `self.initial_data` is generally safe here for unvalidated data.

            if 'flow' in self.initial_data:
                flow_id_from_input = self.initial_data['flow']
                try:
                    # initial_data for PrimaryKeyRelatedField might already be an instance if it passed basic validation
                    if isinstance(flow_id_from_input, Flow):
                        flow_instance = flow_id_from_input
                    else: # Assume it's a PK
                        flow_instance = Flow.objects.get(pk=int(flow_id_from_input))
                except (Flow.DoesNotExist, ValueError, TypeError):
                    # This error should ideally be caught by the 'flow' field's own validation.
                    # If we reach here, it implies the flow PK was somehow invalid but passed other checks.
                    # We can let this pass and rely on object-level validate or save to fail,
                    # or raise a less specific error as this validator's focus is 'is_entry_point'.
                    # For robustness, we assume 'flow' field itself is validated elsewhere.
                    return value # Cannot validate if flow is invalid
            elif self.instance and self.instance.flow: # Updating, and 'flow' field itself is not being changed
                flow_instance = self.instance.flow
            
            if flow_instance:
                query = FlowStep.objects.filter(flow=flow_instance, is_entry_point=True)
                if self.instance and self.instance.pk: # Exclude self if updating an existing instance
                    query = query.exclude(pk=self.instance.pk)
                if query.exists():
                    # This error is specific to the 'is_entry_point' field.
                    raise serializers.ValidationError(
                        f"Flow '{flow_instance.name}' already has an entry point. Only one is allowed."
                    )
        return value


class FlowSerializer(serializers.ModelSerializer):
    """
    Serializer for Flow. Includes entry point ID and step count for read operations.
    """
    entry_point_step_id = serializers.SerializerMethodField(read_only=True)
    steps_count = serializers.IntegerField(source='steps.count', read_only=True)
    # Example for full nested steps (can be large, use with caution for list views)
    # steps = FlowStepSerializer(many=True, read_only=True, source='steps')

    class Meta:
        model = Flow
        fields = [
            'id', 'name', 'description', 'is_active',
            'trigger_keywords', # Expects list of strings from frontend
            'entry_point_step_id',
            'steps_count',
            # 'steps', # If including full nested steps
            'created_at', 'updated_at'
        ]
        read_only_fields = ('id', 'created_at', 'updated_at', 'entry_point_step_id', 'steps_count')

    def get_entry_point_step_id(self, obj: Flow) -> int | None:
        # Assuming 'steps' is the related_name from FlowStep.flow
        entry_step = obj.steps.filter(is_entry_point=True).first()
        return entry_step.id if entry_step else None

    def validate_trigger_keywords(self, value: list) -> list:
        if not isinstance(value, list):
            raise serializers.ValidationError("Trigger keywords must be a list.")
        if not all(isinstance(item, str) for item in value):
            raise serializers.ValidationError("All items in trigger_keywords must be strings.")
        if any(not keyword.strip() for keyword in value): # Ensure no empty or whitespace-only strings
            raise serializers.ValidationError("Trigger keywords cannot be empty or just whitespace.")
        return value


class ContactFlowStateSerializer(serializers.ModelSerializer):
    """
    Serializer for ContactFlowState.
    Typically read-only from an API perspective as this state is managed internally
    by the flow execution logic.
    """
    contact_whatsapp_id = serializers.CharField(source='contact.whatsapp_id', read_only=True)
    contact_name = serializers.CharField(source='contact.name', read_only=True) # Assumes Contact model has 'name'
    current_flow_name = serializers.CharField(source='current_flow.name', read_only=True)
    current_step_name = serializers.CharField(source='current_step.name', read_only=True)

    class Meta:
        model = ContactFlowState
        fields = [
            'id',
            'contact', # Serialized as PK
            'contact_whatsapp_id',
            'contact_name',
            'current_flow', # Serialized as PK
            'current_flow_name',
            'current_step', # Serialized as PK
            'current_step_name',
            'flow_context_data',
            'started_at',
            'last_updated_at'
        ]
        read_only_fields = fields # Makes all fields read-only by default


class WhatsAppFlowSerializer(serializers.ModelSerializer):
    """
    Serializer for WhatsAppFlow model.
    Handles CRUD operations for WhatsApp interactive flow definitions.
    """
    sync_status_display = serializers.CharField(source='get_sync_status_display', read_only=True)
    meta_app_config_name = serializers.CharField(source='meta_app_config.name', read_only=True)
    flow_definition_name = serializers.CharField(source='flow_definition.name', read_only=True, default=None)

    class Meta:
        model = WhatsAppFlow
        fields = [
            'id', 'name', 'friendly_name', 'description',
            'flow_id', 'flow_json', 'sync_status', 'sync_status_display',
            'sync_error', 'version', 'is_active',
            'meta_app_config', 'meta_app_config_name',
            'flow_definition', 'flow_definition_name',
            'created_at', 'updated_at', 'last_synced_at',
        ]
        read_only_fields = (
            'id', 'flow_id', 'sync_status', 'sync_status_display',
            'sync_error', 'meta_app_config_name', 'flow_definition_name',
            'created_at', 'updated_at', 'last_synced_at',
        )

    def validate_flow_json(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Flow JSON must be a JSON object (dictionary).")
        if 'version' not in value:
            raise serializers.ValidationError("Flow JSON must include a 'version' field.")
        if 'screens' not in value or not isinstance(value.get('screens'), list):
            raise serializers.ValidationError("Flow JSON must include a 'screens' list.")
        if not value['screens']:
            raise serializers.ValidationError("Flow JSON must contain at least one screen.")
        return value


class WhatsAppFlowResponseSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for WhatsAppFlowResponse model.
    """
    whatsapp_flow_name = serializers.CharField(source='whatsapp_flow.name', read_only=True)
    contact_display = serializers.SerializerMethodField()

    class Meta:
        model = WhatsAppFlowResponse
        fields = [
            'id', 'whatsapp_flow', 'whatsapp_flow_name',
            'contact', 'contact_display', 'flow_token',
            'response_data', 'is_processed', 'processing_notes',
            'created_at', 'processed_at',
        ]
        read_only_fields = fields

    def get_contact_display(self, obj):
        return obj.contact.name or obj.contact.whatsapp_id