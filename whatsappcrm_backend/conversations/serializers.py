# whatsappcrm_backend/conversations/serializers.py

from rest_framework import serializers
from .models import Contact, Message
# from meta_integration.serializers import MetaAppConfigSerializer # If you uncomment associated_app_config

class ContactSerializer(serializers.ModelSerializer):
    """
    Serializer for the Contact model.
    """
    # associated_app_config_details = MetaAppConfigSerializer(source='associated_app_config', read_only=True) # Example if FK is active

    class Meta:
        model = Contact
        fields = [
            'id',
            'whatsapp_id',
            'name',
            # 'associated_app_config', # ID of the config
            # 'associated_app_config_details', # Full details of the config
            'first_seen',
            'last_seen',
            'is_blocked',
            # 'custom_fields',
            # 'current_flow_state',
        ]
        read_only_fields = ('id', 'first_seen', 'last_seen') # whatsapp_id might also be read_only after creation

    # You could add a method to validate whatsapp_id format if needed
    # def validate_whatsapp_id(self, value):
    #     # Add validation logic for WhatsApp ID format
    #     if not value.isdigit() or len(value) < 10: # Basic example
    #         raise serializers.ValidationError("Invalid WhatsApp ID format.")
    #     return value

class MessageSerializer(serializers.ModelSerializer):
    """
    Serializer for the Message model.
    """
    contact_details = ContactSerializer(source='contact', read_only=True) # Nested contact details for read operations
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.all(), write_only=True) # For creating/linking messages
    message_type_display = serializers.CharField(source='get_message_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    direction_display = serializers.CharField(source='get_direction_display', read_only=True)
    # app_config_details = MetaAppConfigSerializer(source='app_config', read_only=True) # Example if FK is active

    class Meta:
        model = Message
        fields = [
            'id',
            'contact', # Write-only ID for associating message
            'contact_details', # Read-only nested object
            # 'app_config', # ID of the config
            # 'app_config_details', # Full details of the config
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
            'contact_details', # 'app_config_details'
        )
        # For creating outgoing messages, some fields will be set by the backend
        # 'direction' might be set based on the endpoint, 'status' initialized to 'pending'

    def create(self, validated_data):
        # Example: If creating an outgoing message, set direction and initial status
        # This logic might be better handled in the view or a service layer
        # if 'direction' not in validated_data: # Or based on some other logic
        #     validated_data['direction'] = 'out'
        # if 'status' not in validated_data:
        #     validated_data['status'] = 'pending'
        
        message = Message.objects.create(**validated_data)
        return message

class MessageListSerializer(MessageSerializer):
    """
    A more concise serializer for listing Messages, potentially excluding bulky fields.
    """
    class Meta(MessageSerializer.Meta):
        fields = [
            f for f in MessageSerializer.Meta.fields if f not in ['content_payload', 'error_details']
        ] + ['content_preview'] # Add a custom preview field
        read_only_fields = fields


    content_preview = serializers.SerializerMethodField()

    def get_content_preview(self, obj):
        if obj.text_content:
            return (obj.text_content[:100] + '...') if len(obj.text_content) > 100 else obj.text_content
        elif obj.message_type != 'text' and isinstance(obj.content_payload, dict):
            if obj.message_type == 'interactive' and obj.content_payload.get('type'):
                return f"Interactive: {obj.content_payload.get('type')}"
            if obj.content_payload.get('caption'): # For media
                 caption = obj.content_payload.get('caption')
                 return (f"[{obj.message_type.capitalize()}] {caption[:70]}" + ('...' if len(caption) > 70 else ''))
            return f"({obj.message_type.capitalize()} message)"
        return "N/A"

class ContactDetailSerializer(ContactSerializer):
    """
    Contact serializer that includes a list of recent messages.
    """
    recent_messages = MessageListSerializer(many=True, read_only=True, source='messages_preview') # Use a property/method on model

    class Meta(ContactSerializer.Meta):
        fields = ContactSerializer.Meta.fields + ['recent_messages']

    # The 'messages_preview' source would refer to a method or property on the Contact model, e.g.:
    # @property
    # def messages_preview(self):
    #     return self.messages.order_by('-timestamp')[:10] # Get last 10 messages
