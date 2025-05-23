# media_manager/models.py
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
import mimetypes
import logging
import os

# Import MetaAppConfig to fetch credentials
from meta_integration.models import MetaAppConfig
# Import the actual upload utility
from .utils import actual_upload_to_whatsapp_api

logger = logging.getLogger(__name__)

class MediaAsset(models.Model):
    STATUS_CHOICES = [
        ('local', 'Local Only - Pending Upload'),
        ('uploading', 'Uploading to WhatsApp...'),
        ('synced', 'Synced with WhatsApp'),
        ('error_upload', 'Initial Upload Error'),
        ('expired', 'WhatsApp ID Potentially Expired'),
        ('error_resync', 'Re-sync Error'),
    ]
    MEDIA_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
        ('sticker', 'Sticker'),
    ]

    name = models.CharField(
        max_length=255,
        help_text="A descriptive name for this media asset (e.g., 'Welcome Offer Image')."
    )
    file = models.FileField(
        upload_to='whatsapp_media_assets/%Y/%m/',
        help_text="The actual media file."
    )
    media_type = models.CharField(
        max_length=20,
        choices=MEDIA_TYPE_CHOICES,
        help_text="The general type of media."
    )
    mime_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="Specific MIME type. Auto-detected if blank."
    )
    file_size = models.PositiveIntegerField(
        null=True, blank=True, editable=False, help_text="File size in bytes."
    )
    whatsapp_media_id = models.CharField(
        max_length=255,
        blank=True, null=True,
        db_index=True,
        help_text="WhatsApp Media ID. Updated upon successful sync."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='local',
        db_index=True,
        help_text="Sync status with WhatsApp."
    )
    uploaded_to_whatsapp_at = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="Last successful sync with WhatsApp."
    )
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_media_type_display()})"

    def clean(self):
        super().clean()
        if self.file and hasattr(self.file, 'size'):
            # Example: General 100MB limit
            max_size_bytes = 100 * 1024 * 1024
            if self.file.size > max_size_bytes:
                raise ValidationError(f"File size ({self.file.size // (1024*1024)}MB) cannot exceed {max_size_bytes // (1024*1024)}MB.")

    def save(self, *args, **kwargs):
        if self.pk:
            try:
                old_instance = MediaAsset.objects.get(pk=self.pk)
                if old_instance.file != self.file and self.file: # File has changed
                    logger.info(f"File changed for MediaAsset {self.pk} ('{self.name}'). Resetting WhatsApp sync status.")
                    self.whatsapp_media_id = None
                    self.uploaded_to_whatsapp_at = None
                    self.status = 'local' # Mark for re-upload
            except MediaAsset.DoesNotExist:
                pass

        if self.file and hasattr(self.file, 'size'):
            self.file_size = self.file.size
            if not self.mime_type: # Auto-detect MIME type
                self.mime_type = mimetypes.guess_type(self.file.name)[0] or 'application/octet-stream'
        super().save(*args, **kwargs)

    def is_whatsapp_id_potentially_expired(self, days_valid=29):
        if not self.uploaded_to_whatsapp_at or not self.whatsapp_media_id:
            return True # No ID or never uploaded means it needs syncing
        return self.uploaded_to_whatsapp_at < (timezone.now() - timezone.timedelta(days=days_valid))

    def sync_with_whatsapp(self, force_reupload=False, config: MetaAppConfig = None):
        logger.info(f"Initiating sync_with_whatsapp for MediaAsset {self.pk} ('{self.name}'). Force reupload: {force_reupload}")

        if not self.file or not self.file.path: # Check if file exists and has a path
            self.status = 'error_upload'
            self.notes = "Cannot sync: File is missing or not saved to disk (no path)."
            self.save(update_fields=['status', 'notes'])
            logger.error(f"MediaAsset {self.pk} ('{self.name}'): File is missing or has no path.")
            return False

        if not force_reupload and self.status == 'synced' and not self.is_whatsapp_id_potentially_expired():
            logger.info(f"MediaAsset {self.pk} ('{self.name}'): Already synced and ID not expired. Skipping sync.")
            return True

        active_config = config
        if not active_config:
            try:
                active_config = MetaAppConfig.objects.get_active_config()
                logger.info(f"Using active MetaAppConfig: {active_config.name}")
            except (MetaAppConfig.DoesNotExist, MetaAppConfig.MultipleObjectsReturned) as e:
                self.status = 'error_upload' if self.status == 'local' else 'error_resync'
                self.notes = f"Cannot sync: MetaAppConfig issue. {e}"
                self.save(update_fields=['status', 'notes'])
                logger.error(f"MediaAsset {self.pk} ('{self.name}'): MetaAppConfig issue. {e}")
                return False

        self.status = 'uploading'
        self.save(update_fields=['status']) # Save status before long operation

        new_media_id = None
        try:
            new_media_id = actual_upload_to_whatsapp_api(
                file_path=self.file.path,
                mime_type=self.mime_type or 'application/octet-stream', # Ensure mime_type is passed
                phone_number_id=active_config.phone_number_id,
                access_token=active_config.access_token,
                api_version=active_config.api_version
            )

            if new_media_id:
                self.whatsapp_media_id = new_media_id
                self.uploaded_to_whatsapp_at = timezone.now()
                self.status = 'synced'
                self.notes = f"Successfully synced with WhatsApp on {self.uploaded_to_whatsapp_at.strftime('%Y-%m-%d %H:%M')}."
                logger.info(f"MediaAsset {self.pk} ('{self.name}'): Synced. WA ID: {self.whatsapp_media_id}")
                # Update all relevant fields
                self.save(update_fields=['whatsapp_media_id', 'uploaded_to_whatsapp_at', 'status', 'notes'])
                return True
            else:
                # Error already logged by actual_upload_to_whatsapp_api
                self.status = 'error_upload' if self.status == 'uploading' else 'error_resync'
                self.notes = "WhatsApp upload failed (no media ID returned). Check logs from utility function."
                logger.warning(f"MediaAsset {self.pk} ('{self.name}'): {self.notes}")
                self.save(update_fields=['status', 'notes'])
                return False

        except Exception as e: # Catch any other unexpected error from the utility or during processing
            self.status = 'error_upload' if self.status == 'uploading' else 'error_resync'
            self.notes = f"Unexpected error during WhatsApp sync: {e}"
            logger.error(f"MediaAsset {self.pk} ('{self.name}'): Unexpected WhatsApp sync error. {e}", exc_info=True)
            self.save(update_fields=['status', 'notes'])
            return False

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Media Asset"
        verbose_name_plural = "Media Assets"