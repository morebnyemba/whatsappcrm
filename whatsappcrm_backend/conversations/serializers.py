# whatsappcrm_backend/conversations/serializers.py

from rest_framework import serializers
from .models import Contact, Message
from customer_data.serializers import CustomerProfileSerializer # <--- IMPORT CustomerProfileSerializer

class ContactSerializer(serializers.ModelSerializer):
    """
    Serializer for basic Contact model information.
    """
    # If you have a method on the model to get a display name or prefer contact.name
    # display_name = serializers.CharField(source='get_display_name', read_only=True) # Example

    class Meta:
        model = Contact
        fields = [
            'id',
            'whatsapp_id',
            'name',
            'first_seen', # This is the contact creation timestamp
            'last_seen',
            'is_blocked',
            'needs_human_intervention', # From your updated Contact model
            'intervention_requested_at', # From your updated Contact model
            # 'display_name', # If you add a property for it
        ]
        read_only_fields = ('id', 'first_seen', 'last_seen', 'intervention_requested_at')

    # Example validation if you need it (not strictly required by current setup)
    # def validate_whatsapp_id(self, value):
    #     if not re.match(r"^\+?\d{10,15}$", value): # Basic international phone number regex
    #         raise serializers.ValidationError("Invalid WhatsApp ID format.")
    #     return value

class MessageSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for the Message model.
    """
    # For read operations, showing basic contact details with the message
    contact_details = ContactSerializer(source='contact', read_only=True)
    # For write operations (creating a message), frontend will send contact PK
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.all(), write_only=True)
    
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    direction_display = serializers.CharField(source='get_direction_display', read_only=True)

    class Meta:
        model = Message
        fields = [
            'id',
            'contact', # Write-only ID for associating message
            'contact_details', # Read-only nested object for display
            'wamid',
            'direction',
            'direction_display',
            'message_type',
            'message_type_display',
            'content_payload', # Full payload
            'text_content', # Extracted text
            'timestamp',
            'status',
            'status_display',
            'status_timestamp',
            'error_details',
            'is_internal_note',
        ]
        read_only_fields = (
            'id', 'wamid', 'timestamp', 'status_timestamp', 'error_details',
            'message_type_display', 'status_display', 'direction_display',
            'contact_details',
        )

    def create(self, validated_data):
        # This create method is for when your frontend POSTs to /crm-api/conversations/messages/
        # to send an outgoing message.
        # The actual sending via WhatsApp API should be handled by a Celery task
        # triggered from the MessageViewSet's perform_create method.

        # Set defaults for outgoing messages created via API
        validated_data['direction'] = 'out'
        validated_data['status'] = 'pending_dispatch' # Or 'pending_send'
        if 'timestamp' not in validated_data:
             validated_data['timestamp'] = timezone.now()

        message = Message.objects.create(**validated_data)
        
        # Trigger Celery task to send the message
        # from meta_integration.tasks import send_whatsapp_message_task
        # from meta_integration.models import MetaAppConfig
        # active_config = MetaAppConfig.objects.get_active_config() # Or pass config_id
        # if active_config:
        #     send_whatsapp_message_task.delay(message.id, active_config.id)
        # else:
        #     logger.error(f"No active MetaAppConfig found. Message {message.id} cannot be dispatched.")
        #     message.status = 'failed'
        #     message.error_details = {'error': 'No active MetaAppConfig for sending.'}
        #     message.save()
            
        return message

class MessageListSerializer(MessageSerializer):
    """
    A more concise serializer for listing Messages, excluding bulky fields like full content_payload.
    """
    content_preview = serializers.SerializerMethodField()

    class Meta(MessageSerializer.Meta):
        # Override fields from MessageSerializer.Meta
        fields = [
            'id',
            # 'contact', # Usually not needed in a list if messages are already filtered by contact
            'contact_details', # Or just contact_id and contact_name if contact_details is too much
            'wamid',
            'direction',
            'direction_display',
            'message_type',
            'message_type_display',
            'timestamp',
            'status',
            'status_display',
            'content_preview', # Custom preview field
            'is_internal_note',
        ]
        # read_only_fields are inherited and all listed fields are effectively read_only here.

    def get_content_preview(self, obj: Message) -> str:
        if obj.text_content:
            return (obj.text_content[:75] + '...') if len(obj.text_content) > 75 else obj.text_content
        
        # Provide more specific previews for common non-text types
        if obj.message_type == 'image': return "[Image]"
        if obj.message_type == 'document': return f"[Document: {obj.content_payload.get('document', {}).get('filename', 'file')}]"
        if obj.message_type == 'audio': return "[Audio]"
        if obj.message_type == 'video': return "[Video]"
        if obj.message_type == 'sticker': return "[Sticker]"
        if obj.message_type == 'location': return "[Location Shared]"
        if obj.message_type == 'contacts': return "[Contact Card Shared]"
        
        if obj.message_type == 'interactive' and isinstance(obj.content_payload, dict):
            interactive_type = obj.content_payload.get('type')
            if interactive_type == 'button_reply' and obj.content_payload.get('button_reply'):
                return f"Button Click: {obj.content_payload['button_reply'].get('title', obj.content_payload['button_reply'].get('id'))}"
            if interactive_type == 'list_reply' and obj.content_payload.get('list_reply'):
                return f"List Selection: {obj.content_payload['list_reply'].get('title', obj.content_payload['list_reply'].get('id'))}"
            return f"Interactive: {interactive_type or 'message'}"
        
        if obj.message_type == 'button': # This is for user's button *reply*
             if isinstance(obj.content_payload, dict) and obj.content_payload.get('button', {}).get('text'):
                 return f"Button Reply: {obj.content_payload['button']['text']}"
             return "Button Reply"

        if obj.message_type == 'system' and isinstance(obj.content_payload, dict) and obj.content_payload.get('system', {}).get('body'):
            return f"System: {obj.content_payload['system']['body']}"

        return f"({obj.get_message_type_display()})"


class ContactDetailSerializer(ContactSerializer):
    """
    Contact serializer that includes the nested CustomerProfile 
    and a list of recent messages for detailed views.
    """
    customer_profile = CustomerProfileSerializer(read_only=True) # <--- NESTED PROFILE
    recent_messages = MessageListSerializer(many=True, read_only=True, source='get_recent_messages_for_serializer') 
    # 'get_recent_messages_for_serializer' should be a method on your Contact model

    class Meta(ContactSerializer.Meta):
        # Inherit fields from ContactSerializer and add new ones
        fields = ContactSerializer.Meta.fields + ['customer_profile', 'recent_messages']
        # read_only_fields are inherited from ContactSerializer.Meta.
        # 'customer_profile' and 'recent_messages' are defined as read_only=True here.