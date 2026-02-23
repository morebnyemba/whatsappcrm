# whatsappcrm_backend/flows/models.py

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
# from conversations.models import Contact # String reference 'conversations.Contact' is used below
# from meta_integration.models import MetaAppConfig # Not directly used in these models for now

import logging
logger = logging.getLogger(__name__)

class Flow(models.Model):
    """
    Represents a complete conversational flow.
    """
    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Unique name for this flow."
    )
    description = models.TextField(
        blank=True, null=True,
        help_text="A brief description of what this flow does."
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Is this flow currently active and can be triggered?"
    )
    trigger_keywords = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of keywords/phrases that can trigger this flow "
            "(e.g., [\"hello\", \"start session\"]). Case-insensitive 'contains' match."
        )
    )
    requires_login = models.BooleanField(
        default=False,
        help_text="If true, contacts must be logged in (have an active session) to access this flow."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.trigger_keywords, list):
            raise ValidationError({
                'trigger_keywords': _("Trigger keywords must be a list.")
            })
        if not all(isinstance(keyword, str) for keyword in self.trigger_keywords):
            raise ValidationError({
                'trigger_keywords': _("All items in trigger_keywords must be strings.")
            })
        # Ensure no empty strings in trigger_keywords if that's a rule
        if any(not keyword.strip() for keyword in self.trigger_keywords):
            raise ValidationError({
                'trigger_keywords': _("Trigger keywords cannot be empty or just whitespace.")
            })

    def save(self, *args, **kwargs) -> None:
        self.full_clean() # Call full_clean before saving to run all validations
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['name']


class FlowStep(models.Model):
    """
    Represents a single step or node within a Flow.
    """
    STEP_TYPE_CHOICES = [
        ('send_message', _('Send Message')),
        ('question', _('Ask Question')),
        ('condition', _('Conditional Branch')),
        ('action', _('Perform Action')),
        ('wait_for_reply', _('Wait for Reply')),
        ('end_flow', _('End Flow')),
        ('start_flow_node', _('Start Flow Node')),
        ('human_handover', _('Handover to Human Agent')), # <-- Ensure this is present if you use it
    ]

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name='steps')
    name = models.CharField(
        max_length=255,
        help_text="Descriptive name for this step (e.g., 'Welcome Message', 'Ask Email')."
    )
    step_type = models.CharField(max_length=50, choices=STEP_TYPE_CHOICES)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON configuration for this step, structure depends on step_type."
    )
    is_entry_point = models.BooleanField(
        default=False,
        help_text="Is this the first step of the flow? Only one step per flow should be an entry point."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.flow.name} - Step: {self.name} ({self.get_step_type_display()})"

    def clean(self) -> None:
        super().clean()
        # Ensure only one entry point per flow
        if self.is_entry_point:
            query = FlowStep.objects.filter(flow=self.flow, is_entry_point=True)
            if self.pk: # If instance is being updated
                query = query.exclude(pk=self.pk)
            if query.exists():
                raise ValidationError({
                    'is_entry_point': _(f"Flow '{self.flow.name}' already has an entry point. Only one is allowed.")
                })

        # Basic config validation based on step_type
        if not isinstance(self.config, dict):
            raise ValidationError({'config': _("Config must be a valid JSON object (dictionary).")})

        if self.step_type == 'send_message':
            # As per your services.py, the FlowStep.config *is* the message_config if flat,
            # or it's nested under a "message_config" key.
            # Assuming the flatter structure based on recent discussion on webhook output:
            # FlowStep.config = {"message_type": "text", "text": {"body": "..."}}
            if not self.config.get('message_type'):
                raise ValidationError({
                    'config': _("For 'send_message' steps, the config must include a 'message_type' key.")
                })
            # You could add more checks here, e.g., if 'message_type' is 'text', ensure 'text' key exists
            # if self.config.get('message_type') == 'text' and 'text' not in self.config:
            #     raise ValidationError({'config': _("For text messages, config must include a 'text' object.")})

        elif self.step_type == 'question':
            # Assuming config for 'question' nests things like:
            # FlowStep.config = {"message_config": {...}, "reply_config": {...}}
            if not self.config.get('message_config') or not self.config.get('reply_config'):
                raise ValidationError({
                    'config': _("For 'question' steps, config must include 'message_config' and 'reply_config'.")
                })
        elif self.step_type == 'action':
            actions_to_run = self.config.get('actions_to_run')
            if not isinstance(actions_to_run, list):
                raise ValidationError({
                    'config': _("For 'action' steps, config must include 'actions_to_run' as a list.")
                })
        # Add more step_type specific config validations as your system evolves.

    def save(self, *args, **kwargs) -> None:
        self.full_clean() # This calls self.clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['flow', 'created_at']
        unique_together = [['flow', 'name']]


class FlowTransition(models.Model):
    """
    Defines a transition from one FlowStep to another.
    """
    current_step = models.ForeignKey(
        FlowStep,
        on_delete=models.CASCADE,
        related_name='outgoing_transitions'
    )
    next_step = models.ForeignKey(
        FlowStep,
        on_delete=models.CASCADE,
        related_name='incoming_transitions',
        help_text="The step to transition to if conditions are met."
    )
    condition_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON configuration for the condition that triggers this transition."
    )
    priority = models.IntegerField(
        default=0,
        help_text="Order of evaluation for transitions from the same step (lower numbers evaluated first)."
    )

    def __str__(self) -> str:
        return (f"From '{self.current_step.name}' to '{self.next_step.name}' "
                f"(Flow: {self.current_step.flow.name if self.current_step else 'N/A'}, Prio: {self.priority})")

    def clean(self) -> None:
        super().clean()
        if self.current_step and self.next_step:
            if self.current_step.flow_id != self.next_step.flow_id:
                raise ValidationError(
                    _("The current_step and next_step must belong to the same flow.")
                )
            # Consider if direct self-transitions should be disallowed without specific conditions
            # if self.current_step_id == self.next_step_id:
            #     raise ValidationError(_("A step cannot transition directly to itself without a meaningful condition."))

        if not isinstance(self.condition_config, dict):
            raise ValidationError({'condition_config': _("Condition config must be a valid JSON object (dictionary).")})

        # Basic validation for condition_config
        condition_type = self.condition_config.get('type')
        if condition_type: # If a type is specified, it shouldn't be an empty string
            if not isinstance(condition_type, str) or not condition_type.strip():
                 raise ValidationError({'condition_config': _("Condition 'type' must be a non-empty string if provided.")})
        # Add more validation based on known condition_types if needed
        # e.g., if condition_type == 'user_reply_matches_keyword', ensure 'keyword' key exists

    def save(self, *args, **kwargs) -> None:
        self.full_clean() # Ensure model-level validation is run
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['current_step', 'priority']
        # unique_together could be useful if you don't want identical transitions
        # from one step to another with the same priority, unless conditions differ significantly.
        # For now, relying on priority and distinct condition_configs.


class ContactFlowState(models.Model):
    """
    Tracks the current state of a Contact within a specific Flow.
    """
    contact = models.OneToOneField(
        'conversations.Contact',
        on_delete=models.CASCADE,
        related_name='flow_state',
        help_text="The contact engaged in the flow. A contact can only be in one flow state at a time."
    )
    current_flow = models.ForeignKey(
        Flow,
        on_delete=models.CASCADE,
        help_text="The flow this contact is currently engaged in."
    )
    current_step = models.ForeignKey(
        FlowStep,
        on_delete=models.CASCADE, # If a step is deleted, the contact's state in that flow is invalid.
        help_text="The current step the contact is at in this flow."
    )
    flow_context_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Data collected from the user or set during this flow instance (e.g., answers to questions)."
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Ensure flow_context_data is JSON serializable before saving
        if self.flow_context_data:
            from customer_data.utils import _recursively_clean_json_data # Import here to avoid circular dependency
            try:
                self.flow_context_data = _recursively_clean_json_data(self.flow_context_data)
            except Exception as e:
                logger.error(f"Error cleaning flow_context_data for ContactFlowState {self.pk}: {e}", exc_info=True)
                # Optionally, re-raise or set to empty dict if cleaning fails
                raise
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        contact_str = str(self.contact) if self.contact else "Unknown Contact"
        step_name = self.current_step.name if self.current_step else "Unknown Step"
        flow_name = self.current_flow.name if self.current_flow else "Unknown Flow"
        return f"{contact_str} is at '{step_name}' in flow '{flow_name}'"

    # No custom clean() method needed here unless specific cross-field invariants
    # for ContactFlowState itself are defined beyond what FKs and OneToOneField enforce.
    # The default save() is usually sufficient. If you add a clean() method, also add full_clean() to save().

    class Meta:
        verbose_name = "Contact Flow State"
        verbose_name_plural = "Contact Flow States"
        # The OneToOneField on 'contact' already ensures a contact can only have one flow_state.
        # If you ever changed 'contact' to a ForeignKey, then the unique_together below
        # might become relevant again to ensure a contact is only in one *active* flow at a time.
        # unique_together = [['contact', 'current_flow']]