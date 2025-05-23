# whatsappcrm_backend/meta_integration/models.py

from django.db import models
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)

class MetaAppConfigManager(models.Manager):
    def get_active_config(self):
        try:
            return self.get(is_active=True)
        except MetaAppConfig.DoesNotExist:
            logger.error("No active Meta App Configuration found in the database.")
            raise
        except MetaAppConfig.MultipleObjectsReturned:
            logger.error("Multiple Meta App Configurations are marked as active. Please ensure only one is active.")
            raise

class MetaAppConfig(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="A descriptive name for this configuration (e.g., 'Primary Business Account', 'Test Account')"
    )
    verify_token = models.CharField(
        max_length=255,
        help_text="The verify token you set in the Meta App Dashboard for webhook verification."
    )
    access_token = models.TextField(
        help_text="The Page Access Token or System User Token for sending messages."
    )
    phone_number_id = models.CharField(
        max_length=50,
        help_text="The Phone Number ID from which messages will be sent."
    )
    waba_id = models.CharField(
        max_length=50,
        verbose_name="WhatsApp Business Account ID (WABA ID)",
        help_text="Your WhatsApp Business Account ID."
    )
    api_version = models.CharField(
        max_length=10,
        default="v19.0",
        help_text="The Meta Graph API version (e.g., 'v19.0')."
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Set to True if this is the currently active configuration. Only one configuration should be active."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MetaAppConfigManager()

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"

    def clean(self):
        if self.is_active:
            active_configs = MetaAppConfig.objects.filter(is_active=True).exclude(pk=self.pk)
            if active_configs.exists():
                raise ValidationError(
                    "Another configuration is already active. Please deactivate it before activating this one."
                )
        super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Meta App Configuration"
        verbose_name_plural = "Meta App Configurations"
        ordering = ['-is_active', 'name']


class WebhookEventLog(models.Model):
    """
    Stores all incoming webhook events from Meta for auditing and reprocessing if needed.
    """
    EVENT_TYPE_CHOICES = [
        ('message', 'Message Received'),
        ('message_status', 'Message Status Update'),
        ('template_status', 'Message Template Status Update'),
        ('account_update', 'Account Update'),
        ('referral', 'Referral Event'), # When a user messages from an Ad with referral data
        ('system', 'System Message'), # E.g. user changed number
        ('flow_response', 'Flow Response'), # Specific to Meta Flows
        ('security', 'Security Notification'),
        ('error', 'Error Notification'),
        ('unknown', 'Unknown Event Type'),
    ]

    # A unique ID for the event if provided by Meta (e.g., message ID for messages, or a generated one for others)
    # This might not always be present or unique across all event types, so use with caution as a primary key.
    event_identifier = models.CharField(max_length=255, blank=True, null=True, db_index=True, help_text="A unique identifier for the event if available (e.g., wamid for messages).")
    app_config = models.ForeignKey(
        MetaAppConfig,
        on_delete=models.SET_NULL, # Keep log even if config is deleted
        null=True,
        blank=True,
        help_text="Configuration used when this event was received, if identifiable."
    )
    waba_id_received = models.CharField(max_length=50, blank=True, null=True, help_text="WABA ID from the webhook payload.")
    phone_number_id_received = models.CharField(max_length=50, blank=True, null=True, help_text="Phone Number ID from the webhook payload.")

    event_type = models.CharField(
        max_length=50,
        choices=EVENT_TYPE_CHOICES,
        default='unknown',
        help_text="Categorized type of the webhook event."
    )
    payload_object_type = models.CharField(max_length=100, blank=True, null=True, help_text="The 'object' type from the webhook payload (e.g., 'whatsapp_business_account').")
    payload = models.JSONField(help_text="Full JSON payload received from Meta.")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when the event was processed by a handler.")
    processing_status = models.CharField(
        max_length=50,
        default="pending",
        help_text="Processing status (e.g., pending, processed, error, ignored)."
    )
    processing_notes = models.TextField(blank=True, null=True, help_text="Notes or error messages from processing.")


    def __str__(self):
        return f"{self.get_event_type_display()} ({self.event_identifier or 'N/A'}) at {self.received_at.strftime('%Y-%m-%d %H:%M:%S')}"

    class Meta:
        verbose_name = "Webhook Event Log"
        verbose_name_plural = "Webhook Event Logs"
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['event_type', 'received_at']),
            models.Index(fields=['processing_status', 'event_type']),
        ]
