# media_manager/serializers.py
from rest_framework import serializers
from .models import MediaAsset
import mimetypes # For validating/guessing mime_type if needed

class MediaAssetSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField(read_only=True)
    # 'file' is for upload (write operations).
    # For create, it's required. For update (PATCH/PUT), it's optional.
    # DRF handles this well with ModelViewSet: if 'file' is not in PATCH data, it's not updated.
    # If it is in PATCH data, it's treated as a new file upload.
    file = serializers.FileField(write_only=True, required=False, allow_null=True)

    # To make media_type user-friendly in API responses, but still validate against choices on input
    media_type_display = serializers.CharField(source='get_media_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MediaAsset
        fields = [
            'id',
            'name',
            'file',  # Write-only for upload
            'file_url', # Read-only for display/preview
            'media_type', # Writable, validated by model's choices
            'media_type_display', # Read-only
            'mime_type', # Read-only, set by model's save method
            'file_size', # Read-only, set by model's save method
            'whatsapp_media_id', # Read-only, set by sync process
            'status', # Read-only, managed by sync process
            'status_display', # Read-only
            'uploaded_to_whatsapp_at', # Read-only
            'notes', # Writable
            'created_at', # Read-only
            'updated_at', # Read-only
        ]
        read_only_fields = (
            'id', 'file_url', 'mime_type', 'file_size',
            'whatsapp_media_id', 'status', 'status_display', 'media_type_display',
            'uploaded_to_whatsapp_at', 'created_at', 'updated_at'
        )
        # Fields that must be provided on create: name, file, media_type
        # 'notes' is optional.

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and hasattr(obj.file, 'url') and request:
            return request.build_absolute_uri(obj.file.url)
        return None

    def validate_file(self, value):
        """
        Custom validation for the uploaded file.
        Model's clean() method will also run, but serializer validation is good for early API errors.
        """
        if value is None and not self.instance: # File is required on create (instance is None)
            raise serializers.ValidationError("A file must be provided when creating a new media asset.")
        
        # Example file size validation (e.g., 50MB, WhatsApp has its own per-type limits)
        # You might want more specific limits based on 'media_type' if provided simultaneously,
        # or let the model's clean method handle more detailed validation.
        max_upload_size = 50 * 1024 * 1024 # 50MB
        if value and value.size > max_upload_size:
            raise serializers.ValidationError(f"File size cannot exceed {max_upload_size // (1024*1024)}MB.")
        
        # Example basic content type validation (you might want a stricter allowlist)
        # main_type = value.content_type.split('/')[0]
        # if main_type not in ['image', 'video', 'audio', 'application']: # application for docs
        #     raise serializers.ValidationError(f"Unsupported file content type: {value.content_type}")
            
        return value

    def validate_media_type(self, value):
        """
        Ensure media_type is one of the allowed choices.
        Model field already does this, but explicit serializer validation is good practice.
        """
        allowed_media_types = [choice[0] for choice in MediaAsset.MEDIA_TYPE_CHOICES]
        if value not in allowed_media_types:
            raise serializers.ValidationError(f"Invalid media_type. Allowed types are: {', '.join(allowed_media_types)}")
        return value

    def validate(self, data):
        """
        Object-level validation.
        'file' is required on POST (create), but optional on PATCH/PUT (update).
        """
        is_create = self.instance is None
        
        if is_create and 'file' not in data:
            raise serializers.ValidationError({"file": "This field is required for creating a new asset."})
        if is_create and 'name' not in data:
            raise serializers.ValidationError({"name": "This field is required."})
        if is_create and 'media_type' not in data:
            raise serializers.ValidationError({"media_type": "This field is required."})
            
        # If media_type is provided, and file is also provided,
        # you could try to do a basic MIME type vs media_type consistency check.
        # For example, if media_type is 'image', the uploaded file's MIME should be image/*
        # This can get complex, so often it's handled by more specialized validation logic
        # or after upload during a processing step.
        # For now, we rely on the model's save to set mime_type correctly.

        return data

    def create(self, validated_data):
        """
        Handle creation of a new MediaAsset.
        The model's save() method will auto-populate file_size and mime_type.
        The status will default to 'local'.
        """
        # 'file_url', 'mime_type', 'file_size', etc., are not expected in validated_data for create
        # as they are read-only or set by the model.
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """
        Handle updates to a MediaAsset.
        If a new 'file' is provided, the model's save() method should handle
        resetting the WhatsApp sync status.
        """
        # If 'file' is in validated_data, a new file was uploaded.
        # The model's save() method (as designed before) will detect this change
        # and reset whatsapp_media_id, uploaded_to_whatsapp_at, and status.
        return super().update(instance, validated_data)