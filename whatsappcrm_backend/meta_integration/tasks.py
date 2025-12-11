# whatsappcrm_backend/meta_integration/tasks.py

import logging
from celery import shared_task
from django.utils import timezone

from .utils import send_whatsapp_message # Your existing function to call Meta API
from .models import MetaAppConfig
from conversations.models import Message, Contact # To update message status

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60) # bind=True gives access to self, retry settings
def send_whatsapp_message_task(self, outgoing_message_id: int, active_config_id: int):
    """
    Celery task to send a WhatsApp message asynchronously.
    Updates the Message object's status based on the outcome.

    Args:
        outgoing_message_id (int): The ID of the outgoing Message object to send.
        active_config_id (int): The ID of the active MetaAppConfig to use for sending.
    """
    logger.info("="*80)
    logger.info(f"TASK START: send_whatsapp_message_task")
    logger.info(f"Message ID: {outgoing_message_id}, Config ID: {active_config_id}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    try:
        logger.debug(f"Fetching Message object (ID: {outgoing_message_id}) from database...")
        outgoing_msg = Message.objects.select_related('contact').get(pk=outgoing_message_id)
        logger.debug(f"Message fetched: Type={outgoing_msg.message_type}, Direction={outgoing_msg.direction}, Contact={outgoing_msg.contact.whatsapp_id}")
        
        logger.debug(f"Fetching MetaAppConfig object (ID: {active_config_id}) from database...")
        active_config = MetaAppConfig.objects.get(pk=active_config_id)
        logger.debug(f"MetaAppConfig fetched: Phone Number ID={active_config.phone_number_id}")
        
    except Message.DoesNotExist:
        logger.error(f"TASK ERROR: Message with ID {outgoing_message_id} not found in database. Task cannot proceed.")
        logger.info("="*80)
        logger.info(f"TASK END: send_whatsapp_message_task - FAILED (Message not found)")
        logger.info("="*80)
        return # Cannot retry if message doesn't exist
    except MetaAppConfig.DoesNotExist:
        logger.error(f"TASK ERROR: MetaAppConfig with ID {active_config_id} not found in database. Task cannot proceed.")
        # Update message status to failed if config is missing
        if 'outgoing_msg' in locals():
            outgoing_msg.status = 'failed'
            outgoing_msg.error_details = {'error': f'MetaAppConfig ID {active_config_id} not found for sending.'}
            outgoing_msg.status_timestamp = timezone.now()
            outgoing_msg.save(update_fields=['status', 'error_details', 'status_timestamp'])
            logger.info(f"Updated Message {outgoing_message_id} status to 'failed'")
        logger.info("="*80)
        logger.info(f"TASK END: send_whatsapp_message_task - FAILED (Config not found)")
        logger.info("="*80)
        return

    if outgoing_msg.direction != 'out':
        logger.warning(f"Message ID {outgoing_message_id} is not an outgoing message (direction={outgoing_msg.direction}). Skipping.")
        logger.info("="*80)
        logger.info(f"TASK END: send_whatsapp_message_task - SKIPPED (Not outgoing)")
        logger.info("="*80)
        return

    # Avoid resending if already sent successfully or in a final failed state without retries
    if outgoing_msg.wamid and outgoing_msg.status == 'sent':
        logger.info(f"Message ID {outgoing_message_id} (WAMID: {outgoing_msg.wamid}) already marked as sent. Skipping resend.")
        logger.info("="*80)
        logger.info(f"TASK END: send_whatsapp_message_task - SKIPPED (Already sent)")
        logger.info("="*80)
        return
    if outgoing_msg.status == 'failed' and self.request.retries >= self.max_retries:
         logger.warning(f"Message ID {outgoing_message_id} already failed and max retries reached. Skipping.")
         logger.info("="*80)
         logger.info(f"TASK END: send_whatsapp_message_task - SKIPPED (Max retries exceeded)")
         logger.info("="*80)
         return


    logger.info(f"Preparing to send WhatsApp message to contact: {outgoing_msg.contact.whatsapp_id}")
    logger.debug(f"Message type: {outgoing_msg.message_type}")

    try:
        # content_payload should contain the 'data' part for send_whatsapp_message
        # and message_type should be the Meta API message type
        if not isinstance(outgoing_msg.content_payload, dict):
            raise ValueError("Message content_payload is not a valid dictionary for sending.")

        logger.info(f"Calling Meta API to send message (type: {outgoing_msg.message_type})...")
        api_response = send_whatsapp_message(
            to_phone_number=outgoing_msg.contact.whatsapp_id,
            message_type=outgoing_msg.message_type, # This should be 'text', 'template', 'interactive'
            data=outgoing_msg.content_payload, # This is the actual data for the type
            config=active_config
        )

        if api_response and api_response.get('messages') and api_response['messages'][0].get('id'):
            outgoing_msg.wamid = api_response['messages'][0]['id']
            outgoing_msg.status = 'sent' # Successfully handed off to Meta
            outgoing_msg.error_details = None # Clear previous errors if any
            logger.info(f"✓ Message sent successfully via Meta API")
            logger.info(f"  WAMID: {outgoing_msg.wamid}")
            logger.info(f"  To: {outgoing_msg.contact.whatsapp_id}")
        else:
            # Handle failure from Meta API
            error_info = api_response or {'error': 'Meta API call failed or returned unexpected response.'}
            logger.error(f"✗ Failed to send message via Meta API")
            logger.error(f"  Response: {error_info}")
            outgoing_msg.status = 'failed'
            outgoing_msg.error_details = error_info
            # Retry logic for certain types of failures could be added here
            # For now, we rely on Celery's built-in retry for RequestException type errors.
            # If Meta returns a specific error code that indicates a retryable issue, handle it.
            # Example: if error_info.get('error', {}).get('code') == SOME_RETRYABLE_CODE:
            #    raise self.retry(exc=ValueError("Meta API retryable error"))

    except Exception as e:
        logger.error(f"TASK ERROR: Exception occurred while sending message: {e}", exc_info=True)
        outgoing_msg.status = 'failed'
        outgoing_msg.error_details = {'error': str(e), 'type': type(e).__name__}
        try:
            # Retry the task if it's a network issue or a temporary problem
            # Celery will automatically retry based on max_retries and default_retry_delay.
            # You might want to customize retry conditions.
            logger.error(f"Retry {self.request.retries + 1}/{self.max_retries} will be attempted in {self.default_retry_delay}s")
            raise self.retry(exc=e) # Re-raise to trigger Celery's retry mechanism
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for sending Message ID {outgoing_message_id}.")
            # Message remains marked as 'failed'
    finally:
        outgoing_msg.status_timestamp = timezone.now()
        outgoing_msg.save(update_fields=['wamid', 'status', 'error_details', 'status_timestamp'])
        logger.debug(f"Updated Message {outgoing_message_id} in database: status={outgoing_msg.status}")
        logger.info("="*80)
        logger.info(f"TASK END: send_whatsapp_message_task - Status: {outgoing_msg.status.upper()}")
        logger.info("="*80)
