# whatsappcrm_backend/customer_data/serializers.py
from rest_framework import serializers
from .models import CustomerProfile
# from conversations.models import Contact # Not strictly needed for this serializer if not doing reverse relations

class CustomerProfileSerializer(serializers.ModelSerializer):
    # You can add read-only fields from the related Contact if needed for context,
    # but typically the main Contact data will come from ContactSerializer.
    # contact_whatsapp_id = serializers.CharField(source='contact.whatsapp_id', read_only=True, allow_null=True)
    # contact_name = serializers.CharField(source='contact.name', read_only=True, allow_null=True)

    class Meta:
        model = CustomerProfile
        # List all fields from your CustomerProfile model
        # 'contact' is the PK (contact_id)
        fields = [
            'contact',
            # 'contact_whatsapp_id',
            # 'contact_name',
            'first_name',
            'last_name',
            'email',
            'secondary_phone_number',
            'ecocash_number', # From your model
            'date_of_birth',
            'gender',
            'company_name',
            'job_title',
            'address_line_1',
            'address_line_2',
            'city',
            'state_province',
            'postal_code',
            'country',
            'lifecycle_stage',
            'acquisition_source',
            'tags',
            'notes',
            'preferences',
            'custom_attributes',
            'created_at',
            'updated_at',
            'last_updated_from_conversation'
        ]
        # 'contact' is the primary key and thus intrinsically linked.
        # It will be represented by the contact's ID.
        # For updates via an endpoint like /profiles/{contact_id}/, 'contact' field won't be in the request body.
        read_only_fields = ('contact', 'created_at', 'updated_at', 'last_updated_from_conversation')

    def validate_tags(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Tags must be a list.")
        if not all(isinstance(tag, str) for tag in value):
            raise serializers.ValidationError("All tags must be strings.")
        return value

    def validate_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Preferences must be a JSON object (dictionary).")
        return value

    def validate_custom_attributes(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Custom attributes must be a JSON object (dictionary).")
        return value