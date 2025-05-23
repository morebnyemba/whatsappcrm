# media_manager/tasks.py
from celery import shared_task
from django.utils import timezone
from django.db.models import Q
import logging

from .models import MediaAsset
# MetaAppConfig might be needed if you pass it explicitly, but model method can fetch it.
# from meta_integration.models import MetaAppConfig

logger = logging.getLogger(__name__)

@shared_task(name="media_manager.tasks.check_and_resync_whatsapp_media")
def check_and_resync_whatsapp_media():
    """
    Periodically checks WhatsApp media assets and attempts to re-sync
    those that are expired, have errored, or were never uploaded.
    """
    logger.info("[Celery Task] Starting periodic check and re-sync of WhatsApp media assets.")
    
    # Fetch active configuration once if you want to pass it to each sync call,
    # though the model method can also fetch it.
    # active_config_instance = None
    # try:
    #     active_config_instance = MetaAppConfig.objects.get_active_config()
    # except Exception as e:
    #     logger.error(f"[Celery Task] Critical error: Cannot fetch active MetaAppConfig. Task aborted. Error: {e}")
    #     return

    # Assets that are synced but whose IDs might have expired (older than 29 days)
    # Or assets that were never synced ('local') or had previous errors.
    thirty_days_ago = timezone.now() - timezone.timedelta(days=29) # More precise for expiry check
    
    assets_needing_attention = MediaAsset.objects.filter(
        Q(status='synced', uploaded_to_whatsapp_at__lt=thirty_days_ago) | # Expired synced
        Q(status='expired') | # Explicitly marked as expired
        Q(status='local') | # Never uploaded
        Q(status__in=['error_upload', 'error_resync']) # Had errors
    ).distinct() # distinct() in case an asset matches multiple Q objects (though unlikely here)

    if not assets_needing_attention.exists():
        logger.info("[Celery Task] No media assets found requiring attention.")
        return

    logger.info(f"[Celery Task] Found {assets_needing_attention.count()} assets requiring attention.")
    
    success_count = 0
    fail_count = 0

    for asset in assets_needing_attention:
        logger.info(f"[Celery Task] Processing MediaAsset {asset.pk} ('{asset.name}'), current status: {asset.status}.")
        # If an asset was synced and is now considered expired by age, update its status first.
        if asset.status == 'synced' and asset.uploaded_to_whatsapp_at and asset.uploaded_to_whatsapp_at < thirty_days_ago:
            logger.info(f"[Celery Task] Marking MediaAsset {asset.pk} as 'expired' due to age.")
            asset.status = 'expired'
            asset.save(update_fields=['status'])
            # The force_reupload=True in sync_with_whatsapp will handle expired status

        # The sync_with_whatsapp method will fetch MetaAppConfig if not passed.
        # Pass active_config_instance if you fetched it once above to avoid repeated DB queries.
        # if asset.sync_with_whatsapp(force_reupload=True, config=active_config_instance):
        if asset.sync_with_whatsapp(force_reupload=True):
            success_count += 1
            logger.info(f"[Celery Task] Successfully synced/re-synced MediaAsset {asset.pk} ('{asset.name}').")
        else:
            fail_count += 1
            logger.error(f"[Celery Task] Failed to sync/re-sync MediaAsset {asset.pk} ('{asset.name}'). Check asset notes/status.")

    logger.info(
        f"[Celery Task] Finished processing. "
        f"Total checked: {assets_needing_attention.count()}. "
        f"Successfully synced/re-synced: {success_count}. "
        f"Failed: {fail_count}."
    )