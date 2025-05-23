# whatsappcrm_backend/meta_integration/serializers.py

from rest_framework import serializers
from .models import MetaAppConfig, WebhookEventLog

class MetaAppConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for the MetaAppConfig model.
    Provides CRUD operations.
    """
    class Meta:
        model = MetaAppConfig
        fields = [
            'id',
            'name',
            'verify_token',
            'access_token', # Be cautious about exposing this directly or ensure proper permissions
            'phone_number_id',
            'waba_id',
            'api_version',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ('id', 'created_at', 'updated_at')
        extra_kwargs = {
            # access_token is sensitive, consider write-only or specific update methods if needed for frontend modification.
            # For now, allowing it to be updated by trusted clients.
            'access_token': {'write_only': False, 'style': {'input_type': 'password'} if serializers.HyperlinkedModelSerializer else {}}, # Mask in browsable API if possible
            'verify_token': {'write_only': False, 'style': {'input_type': 'password'} if serializers.HyperlinkedModelSerializer else {}}, # Mask in browsable API if possible
        }

    def validate(self, data):
        """
        Custom validation to ensure only one config is active.
        This duplicates the model's clean() method logic for the serializer context.
        """
        instance = self.instance # Existing instance during updates

        is_activating = data.get('is_active', instance.is_active if instance else False)

        if is_activating:
            active_configs_query = MetaAppConfig.objects.filter(is_active=True)
            if instance: # If updating an existing instance
                active_configs_query = active_configs_query.exclude(pk=instance.pk)
            
            if active_configs_query.exists():
                raise serializers.ValidationError({
                    "is_active": "Another configuration is already active. Please deactivate it before activating this one."
                })
        return data

    def update(self, instance, validated_data):
        """
        Handle the case where if one config is set to active, others are deactivated.
        """
        if validated_data.get('is_active', False) and not instance.is_active:
            MetaAppConfig.objects.filter(is_active=True).exclude(pk=instance.pk).update(is_active=False)
        
        # If is_active is being set to False, no special handling needed for other instances.
        
        return super().update(instance, validated_data)

    def create(self, validated_data):
        """
        Handle the case where if a new config is created as active, others are deactivated.
        """
        if validated_data.get('is_active', False):
            MetaAppConfig.objects.filter(is_active=True).update(is_active=False)
        return super().create(validated_data)


class WebhookEventLogSerializer(serializers.ModelSerializer):
    """
    Serializer for the WebhookEventLog model.
    Typically used for read-only purposes from the frontend.
    """
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    app_config_name = serializers.CharField(source='app_config.name', read_only=True, allow_null=True)

    class Meta:
        model = WebhookEventLog
        fields = [
            'id',
            'event_identifier',
            'app_config', # Foreign key ID
            'app_config_name', # Human-readable name
            'waba_id_received',
            'phone_number_id_received',
            'event_type',
            'event_type_display', # Human-readable event type
            'payload_object_type',
            'payload', # Could be large, consider excluding or making it optional for list views
            'received_at',
            'processed_at',
            'processing_status',
            'processing_notes'
        ]
        read_only_fields = fields # Make all fields read-only by default for logs


class WebhookEventLogListSerializer(WebhookEventLogSerializer):
    """
    A more concise serializer for listing WebhookEventLogs, excluding the large payload.
    """
    class Meta(WebhookEventLogSerializer.Meta):
        fields = [
            field for field in WebhookEventLogSerializer.Meta.fields if field != 'payload'
        ]
        read_only_fields = fields
