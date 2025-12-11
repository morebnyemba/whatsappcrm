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
    logger.info("="*80)
    logger.info("TASK START: check_and_resync_whatsapp_media (Periodic Media Sync)")
    logger.info("="*80)
    
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
    
    logger.info(f"Querying media assets that need attention (expired, local, or errored)...")
    logger.debug(f"Expiry cutoff date: {thirty_days_ago}")
    
    assets_needing_attention = MediaAsset.objects.filter(
        Q(status='synced', uploaded_to_whatsapp_at__lt=thirty_days_ago) | # Expired synced
        Q(status='expired') | # Explicitly marked as expired
        Q(status='local') | # Never uploaded
        Q(status__in=['error_upload', 'error_resync']) # Had errors
    ).distinct() # distinct() in case an asset matches multiple Q objects (though unlikely here)

    asset_count = assets_needing_attention.count()
    
    if not assets_needing_attention.exists():
        logger.info("No media assets found requiring attention.")
        logger.info("="*80)
        logger.info("TASK END: check_and_resync_whatsapp_media - No assets to sync")
        logger.info("="*80)
        return

    logger.info(f"Found {asset_count} media asset(s) requiring attention")
    
    success_count = 0
    fail_count = 0
    expired_marked_count = 0

    for idx, asset in enumerate(assets_needing_attention, 1):
        logger.info(f"Processing asset {idx}/{asset_count}: ID={asset.pk}, Name='{asset.name}', Status={asset.status}")
        
        # If an asset was synced and is now considered expired by age, update its status first.
        if asset.status == 'synced' and asset.uploaded_to_whatsapp_at and asset.uploaded_to_whatsapp_at < thirty_days_ago:
            logger.info(f"Asset {asset.pk} is synced but older than 29 days. Marking as 'expired'.")
            asset.status = 'expired'
            asset.save(update_fields=['status'])
            expired_marked_count += 1
            # The force_reupload=True in sync_with_whatsapp will handle expired status

        # The sync_with_whatsapp method will fetch MetaAppConfig if not passed.
        # Pass active_config_instance if you fetched it once above to avoid repeated DB queries.
        # if asset.sync_with_whatsapp(force_reupload=True, config=active_config_instance):
        logger.debug(f"Calling asset.sync_with_whatsapp(force_reupload=True) for asset {asset.pk}...")
        if asset.sync_with_whatsapp(force_reupload=True):
            success_count += 1
            logger.info(f"✓ Successfully synced/re-synced asset {asset.pk} ('{asset.name}')")
        else:
            fail_count += 1
            logger.error(f"✗ Failed to sync/re-synced asset {asset.pk} ('{asset.name}')")
            logger.error(f"  Status: {asset.status}, Message: {asset.status_message}")

    logger.info("="*80)
    logger.info(f"TASK END: check_and_resync_whatsapp_media - COMPLETE")
    logger.info(f"Total: {asset_count}, Marked Expired: {expired_marked_count}, Success: {success_count}, Failed: {fail_count}")
    logger.info("="*80)
    
@shared_task(name="media_manager.tasks.trigger_individual_asset_sync") # Give it a unique name
def trigger_media_asset_sync_task(media_asset_id: int, force_reupload: bool = False):
    """
    Task to sync a single MediaAsset with WhatsApp, typically called after upload or manual request.
    """
    logger.info("="*80)
    logger.info(f"TASK START: trigger_media_asset_sync_task")
    logger.info(f"Asset ID: {media_asset_id}, Force Re-upload: {force_reupload}")
    logger.info("="*80)
    
    try:
        logger.debug(f"Fetching MediaAsset {media_asset_id} from database...")
        asset = MediaAsset.objects.get(pk=media_asset_id)
        logger.info(f"Asset found: Name='{asset.name}', Status={asset.status}")
        
        logger.info(f"Calling asset.sync_with_whatsapp(force_reupload={force_reupload})...")
        if asset.sync_with_whatsapp(force_reupload=force_reupload):
            logger.info(f"✓ Successfully synced MediaAsset {asset.pk} ('{asset.name}')")
            logger.info("="*80)
            logger.info(f"TASK END: trigger_media_asset_sync_task - SUCCESS")
            logger.info("="*80)
        else:
            logger.error(f"✗ Failed to sync MediaAsset {asset.pk} ('{asset.name}')")
            logger.error(f"  Status: {asset.status}, Message: {asset.status_message}")
            logger.info("="*80)
            logger.info(f"TASK END: trigger_media_asset_sync_task - FAILED")
            logger.info("="*80)
            
    except MediaAsset.DoesNotExist:
        logger.error(f"TASK ERROR: MediaAsset ID {media_asset_id} not found for individual sync.")
        logger.info("="*80)
        logger.info(f"TASK END: trigger_media_asset_sync_task - FAILED (Asset not found)")
        logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Exception during individual sync for MediaAsset ID {media_asset_id}: {e}", exc_info=True)
        logger.info("="*80)
        logger.info(f"TASK END: trigger_media_asset_sync_task - ERROR")
        logger.info("="*80)
        # Depending on the error, you might want to retry this task too
        # e.g., raise self.retry(exc=e, countdown=60) if task is bound and configured for retries