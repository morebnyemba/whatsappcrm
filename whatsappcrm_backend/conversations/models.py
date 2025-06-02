# whatsappcrm_backend/conversations/models.py

from django.db import models
from django.conf import settings
from django.utils import timezone
# It's good practice to link conversations to the MetaAppConfig if you might have multiple,
# or just to know which configuration handled this conversation.
# from meta_integration.models import MetaAppConfig # Assuming models are in meta_integration

class Contact(models.Model):
    """
    Represents a WhatsApp user (contact).
    """
    whatsapp_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="The user's WhatsApp ID (phone number)."
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Name of the contact, as provided by WhatsApp or manually entered."
    )
    # Link to the MetaAppConfig that this contact is primarily associated with, if applicable
    # This helps if you manage multiple WhatsApp numbers/businesses through the same CRM.
    # associated_app_config = models.ForeignKey(
    #     MetaAppConfig,
    #     on_delete=models.SET_NULL, # Keep contact even if config is deleted
    #     null=True,
    #     blank=True,
    #     help_text="The Meta App Configuration this contact is associated with."
    # )
    
    needs_human_intervention = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Set to true if this contact requires human attention."
    )
    intervention_requested_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp of when human intervention was last requested."
    )
    intervention_resolved_at = models.DateTimeField(  # <<< --- FIELD ADDED HERE ---
        null=True, blank=True,
        help_text="Timestamp of when human intervention was resolved."
    )
    first_seen = models.DateTimeField(auto_now_add=True, help_text="Timestamp of when the contact was first created.")
    last_seen = models.DateTimeField(auto_now=True, help_text="Timestamp of the last interaction (message) with this contact.")
    # You can add more fields like email, company, notes, tags, etc.
    # custom_fields = models.JSONField(default=dict, blank=True, help_text="Custom fields for this contact.")
    is_blocked = models.BooleanField(default=False, help_text="If the CRM has blocked this contact.")
    current_flow_state = models.JSONField(default=dict, blank=True, help_text="Stores the current state of the contact within a flow.")


    def __str__(self):
        return f"{self.name or 'Unknown'} ({self.whatsapp_id})"

    class Meta:
        ordering = ['-last_seen']
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"


class Message(models.Model):
    """
    Represents a single message in a conversation.
    """
    DIRECTION_CHOICES = [
        ('in', 'Incoming'), # Message from contact to business
        ('out', 'Outgoing'), # Message from business to contact
    ]

    MESSAGE_TYPE_CHOICES = [
        # Common types from Meta API
        ('text', 'Text'),
        ('image', 'Image'),
        ('audio', 'Audio'),
        ('video', 'Video'),
        ('document', 'Document'),
        ('sticker', 'Sticker'),
        ('location', 'Location'),
        ('contacts', 'Contacts'), # Shared contact card(s)
        ('interactive', 'Interactive Message'), # List messages, reply buttons, flows
        ('button', 'Button Reply'), # User clicked a quick reply button
        ('system', 'System Message'), # e.g., user changed number, call notifications
        ('unknown', 'Unknown'),
        ('unsupported', 'Unsupported'),
        # CRM internal types
        ('crm_note', 'CRM Internal Note'),
        ('flow_trigger', 'Flow Trigger (Internal)'),
    ]
    triggered_by_flow_step = models.ForeignKey(
        'flows.FlowStep',  # Adjust 'flows.FlowStep' if your app/model name is different
        on_delete=models.SET_NULL,  # Or models.PROTECT, models.CASCADE as appropriate
        null=True,
        blank=True,
        related_name='triggered_messages',
        help_text="The flow step that triggered the creation of this message, if any."
    )
    # Status for outgoing messages, reflecting Meta's statuses
    STATUS_CHOICES = [
        ('pending', 'Pending Send'), # CRM has generated it, not yet sent to Meta
        ('sent', 'Sent to Meta'),    # Meta API accepted it (wamid received)
        ('delivered', 'Delivered to User'),
        ('read', 'Read by User'),
        ('failed', 'Failed to Send'), # Meta reported an error sending
        ('deleted', 'Deleted'), # If Meta supports deleting messages
        # For incoming messages, status might be less relevant or just 'received'
        ('received', 'Received'),
    ]

    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE, # If contact is deleted, delete their messages
        related_name='messages'
    )
    # Link to the MetaAppConfig used for this specific message, if applicable
    # app_config = models.ForeignKey(
    #     MetaAppConfig,
    #     on_delete=models.SET_NULL,
    #     null=True,
    #     blank=True,
    #     help_text="The Meta App Configuration used for sending/receiving this message."
    # )
    wamid = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="WhatsApp Message ID (from Meta), unique for sent/received messages."
    )
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, help_text="Direction of the message." ,default="out")
    message_type = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPE_CHOICES,
        default='text',
        help_text="Type of WhatsApp message."
    )
    # Store the raw message object from Meta for incoming, or the payload sent for outgoing.
    # This is useful for debugging, reprocessing, or accessing fields not explicitly modeled.
    content_payload = models.JSONField(help_text="Raw message payload from/to Meta API.")
    
    # For quick access to text content if it's a text message
    text_content = models.TextField(blank=True, null=True, help_text="Text content if it's a text message.")
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True, help_text="Timestamp of the message (from Meta or when CRM processed it).")
    
    # Status fields for outgoing messages
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending', # Default for outgoing, 'received' for incoming
        help_text="Status of the message."
    )
    status_timestamp = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last status update.")
    error_details = models.JSONField(null=True, blank=True, help_text="Error details if message sending failed.")

    # Timestamps for specific statuses (optional, can be derived from status_timestamp and status)
    # sent_at = models.DateTimeField(null=True, blank=True)
    # delivered_at = models.DateTimeField(null=True, blank=True)
    # read_at = models.DateTimeField(null=True, blank=True)

    # For CRM internal notes or messages not directly from WhatsApp
    is_internal_note = models.BooleanField(default=False)


    def __str__(self):
        direction_arrow = "->" if self.direction == 'out' else "<-"
        contact_name = self.contact.name or self.contact.whatsapp_id
        return f"Msg {self.id} {direction_arrow} {contact_name} ({self.message_type}) at {self.timestamp.strftime('%Y-%m-%d %H:%M')}"

    def save(self, *args, **kwargs):
        # If it's a text message and text_content is not set, try to populate it from content_payload
        if self.message_type == 'text' and not self.text_content and isinstance(self.content_payload, dict):
            if self.direction == 'in': # Incoming message structure
                self.text_content = self.content_payload.get('text', {}).get('body')
            elif self.direction == 'out': # Outgoing message structure
                self.text_content = self.content_payload.get('body') # Assuming 'body' is at the top level of the text object

        # Update contact's last_seen timestamp
        if self.contact_id: # Ensure contact is associated
            # Using update is more efficient as it avoids calling the contact's save() method and signals
            Contact.objects.filter(pk=self.contact_id).update(last_seen=self.timestamp)

        super().save(*args, **kwargs)

    class Meta:
        ordering = ['timestamp'] # Order messages chronologically by default
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        indexes = [
            models.Index(fields=['contact', 'timestamp']),
            models.Index(fields=['wamid']),
            models.Index(fields=['message_type']),
            models.Index(fields=['status', 'direction']),
        ]