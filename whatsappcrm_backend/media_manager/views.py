# media_manager/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils import timezone # For notes timestamp

from .models import MediaAsset
from .serializers import MediaAssetSerializer
from .tasks import trigger_media_asset_sync_task # Celery task launcher

import logging
logger = logging.getLogger(__name__)

class MediaAssetViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing MediaAssets.
    Automatically triggers WhatsApp sync on create and file update.
    Provides a manual action to re-synchronize assets with WhatsApp.
    """
    queryset = MediaAsset.objects.all().order_by('-created_at')
    serializer_class = MediaAssetSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        media_type = params.get('media_type')
        asset_status = params.get('status')

        if media_type:
            valid_media_types = [choice[0] for choice in MediaAsset.MEDIA_TYPE_CHOICES]
            if media_type in valid_media_types:
                queryset = queryset.filter(media_type=media_type)
            else:
                logger.warning(f"Invalid media_type filter received: {media_type}")
        if asset_status:
            valid_statuses = [choice[0] for choice in MediaAsset.STATUS_CHOICES]
            if asset_status in valid_statuses:
                queryset = queryset.filter(status=asset_status)
            else:
                logger.warning(f"Invalid status filter received: {asset_status}")
        return queryset

    def _queue_sync_task(self, asset_instance, action_type="creation"):
        """Helper method to queue the sync task and update asset status."""
        try:
            logger.info(f"API: Automatically queueing sync for MediaAsset {asset_instance.pk} after {action_type}.")
            task_result = trigger_media_asset_sync_task.delay(asset_pk=asset_instance.pk, force_reupload=True)
            
            asset_instance.status = 'uploading' # Set status immediately
            asset_instance.notes = (
                f"Automatic sync task {task_result.id} queued after {action_type} "
                f"at {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}."
            )
            asset_instance.save(update_fields=['status', 'notes'])
            logger.info(f"API: Sync task {task_result.id} queued for MediaAsset {asset_instance.pk}. Asset status set to 'uploading'.")
            return task_result.id
        except Exception as e:
            logger.error(f"API: Failed to queue sync task for MediaAsset {asset_instance.pk} after {action_type}: {e}", exc_info=True)
            # Even if task queuing fails, the asset is saved. Frontend might need to manually trigger sync.
            # Update notes to reflect the failure to queue.
            asset_instance.notes = (
                f"Local {action_type} successful. FAILED to automatically queue sync task. "
                f"Error: {e}. Please trigger sync manually."
            )
            asset_instance.status = 'local' # Or a specific error state if queueing failed
            asset_instance.save(update_fields=['status', 'notes'])
            return None

    def perform_create(self, serializer):
        logger.info(f"API: Creating new MediaAsset '{serializer.validated_data.get('name')}'")
        asset = serializer.save() # Model's save sets initial status, mime_type, file_size
        
        task_id = self._queue_sync_task(asset, action_type="creation")
        
        # Add task_id to response headers or body if needed by frontend
        if hasattr(self, 'headers'): # self.headers might not exist in all test contexts
             self.headers['X-Celery-Task-ID'] = task_id if task_id else ''


    def create(self, request, *args, **kwargs):
        """
        Override create to customize the response message.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer) # This now also queues the task
        
        asset_data = serializer.data # Get data of the created asset
        task_id = self.headers.get('X-Celery-Task-ID', None) if hasattr(self, 'headers') else None

        response_data = {
            'message': f"MediaAsset '{asset_data['name']}' created successfully. Sync with WhatsApp initiated.",
            'asset': asset_data
        }
        if task_id:
            response_data['sync_task_id'] = task_id
        
        headers = self.get_success_headers(serializer.data)
        if task_id: # Also add custom header from perform_create
            headers['X-Celery-Task-ID'] = task_id

        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)


    def perform_update(self, serializer):
        instance = serializer.instance
        # Check if 'file' is part of the incoming validated_data and is not None
        new_file_uploaded = 'file' in serializer.validated_data and serializer.validated_data['file'] is not None
        
        logger.info(f"API: Updating MediaAsset {instance.pk} ('{instance.name}'). New file uploaded: {new_file_uploaded}")
        updated_asset = serializer.save() # Model's save() handles status reset if file changed

        task_id = None
        if new_file_uploaded:
            # If a new file was uploaded, the model's save() should have reset status to 'local'.
            # We then queue a sync task.
            task_id = self._queue_sync_task(updated_asset, action_type="file update")
        
        if hasattr(self, 'headers') and task_id: # self.headers might not exist in all test contexts
             self.headers['X-Celery-Task-ID'] = task_id

        logger.info(f"API: MediaAsset {updated_asset.pk} ('{updated_asset.name}') updated. Current status: '{updated_asset.status}'.")

    def update(self, request, *args, **kwargs):
        """
        Override update to customize the response message, especially if sync is triggered.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        # Check if file is being updated BEFORE perform_update, as perform_update saves.
        new_file_uploaded = 'file' in serializer.validated_data and serializer.validated_data['file'] is not None
        
        self.perform_update(serializer) # This now also queues the task if file changed

        asset_data = serializer.data
        task_id = self.headers.get('X-Celery-Task-ID', None) if hasattr(self, 'headers') else None

        message = f"MediaAsset '{asset_data['name']}' updated successfully."
        if new_file_uploaded:
            message += " File was updated, sync with WhatsApp initiated."

        response_data = {
            'message': message,
            'asset': asset_data
        }
        if task_id:
            response_data['sync_task_id'] = task_id

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}
            
        headers = {}
        if task_id: # Also add custom header from perform_update
            headers['X-Celery-Task-ID'] = task_id

        return Response(response_data, status=status.HTTP_200_OK, headers=headers)


    @action(detail=True, methods=['post'], url_path='sync-with-whatsapp', permission_classes=[permissions.IsAuthenticated])
    def manual_sync_media_asset(self, request, pk=None):
        """
        Custom action to MANUALLY trigger the synchronization of a specific MediaAsset
        with WhatsApp servers via a Celery task.
        """
        asset = self.get_object()
        
        if asset.status == 'uploading':
            return Response(
                {'status': 'conflict', 'message': f"MediaAsset '{asset.name}' (PK: {asset.pk}) is already in the process of uploading/syncing."},
                status=status.HTTP_409_CONFLICT
            )

        logger.info(f"API: Received MANUAL request to sync MediaAsset {asset.pk} ('{asset.name}'). Queueing task.")
        
        try:
            task_result = trigger_media_asset_sync_task.delay(asset_pk=asset.pk, force_reupload=True)
            
            asset.status = 'uploading'
            asset.notes = (
                f"Manual sync task {task_result.id} queued via API "
                f"at {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}."
            )
            asset.save(update_fields=['status', 'notes'])

            logger.info(f"API: Manual sync task {task_result.id} queued for MediaAsset {asset.pk}.")
            return Response(
                {
                    'status': 'sync_initiated',
                    'message': f"Manual synchronization task for MediaAsset '{asset.name}' has been queued.",
                    'task_id': task_result.id,
                    'asset_id': asset.pk,
                    'current_asset_status': asset.status
                },
                status=status.HTTP_202_ACCEPTED
            )
        except Exception as e:
            logger.error(f"API: Failed to queue manual sync task for MediaAsset {asset.pk}: {e}", exc_info=True)
            return Response(
                {'status': 'error', 'message': 'Failed to queue manual synchronization task due to an internal error.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )