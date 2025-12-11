# whatsappcrm_backend/referrals/tasks.py
import logging
from celery import shared_task
from django.contrib.auth import get_user_model

# Assuming a utility function exists to send messages.
from meta_integration.utils import send_whatsapp_message, create_text_message_data

logger = logging.getLogger(__name__)
User = get_user_model()

@shared_task(name="referrals.send_bonus_notification_task")
def send_bonus_notification_task(user_id: int, message: str):
    """
    Sends a WhatsApp notification to a user.
    """
    logger.info("="*80)
    logger.info(f"TASK START: send_bonus_notification_task")
    logger.info(f"User ID: {user_id}")
    logger.info("="*80)
    
    try:
        logger.debug(f"Fetching user {user_id} from database...")
        user = User.objects.select_related('customer_profile__contact').get(id=user_id)
        whatsapp_id = user.customer_profile.contact.whatsapp_id
        
        logger.debug(f"User found: {user.username}, WhatsApp ID: {whatsapp_id}")
        
        if not whatsapp_id:
            logger.warning(f"Cannot send bonus notification to user {user_id}. No WhatsApp ID found.")
            logger.info("="*80)
            logger.info(f"TASK END: send_bonus_notification_task - SKIPPED (No WhatsApp ID)")
            logger.info("="*80)
            return

        logger.info(f"Sending bonus notification to {whatsapp_id}...")
        logger.debug(f"Message content: {str(message)[:100]}..." if message and len(str(message)) > 100 else f"Message content: {message}")
        
        message_data = create_text_message_data(text_body=message)
        result = send_whatsapp_message(to_phone_number=whatsapp_id, message_type='text', data=message_data)
        
        if result and result.get("messages"):
            logger.info(f"✓ Successfully sent bonus notification")
            logger.info(f"  User: {user.username} (ID: {user_id})")
            logger.info(f"  To: {whatsapp_id}")
            logger.info(f"  Meta Message ID: {result['messages'][0]['id']}")
        else:
            logger.error(f"✗ Failed to send bonus notification")
            logger.error(f"  Result: {result}")
        
        logger.info("="*80)
        logger.info(f"TASK END: send_bonus_notification_task - SUCCESS")
        logger.info("="*80)
        
    except User.DoesNotExist:
        logger.error(f"TASK ERROR: User with ID {user_id} not found for sending bonus notification.")
        logger.info("="*80)
        logger.info(f"TASK END: send_bonus_notification_task - FAILED (User not found)")
        logger.info("="*80)
    except Exception as e:
        logger.error(f"TASK ERROR: Exception in send_bonus_notification_task for user {user_id}: {e}", exc_info=True)
        logger.info("="*80)
        logger.info(f"TASK END: send_bonus_notification_task - ERROR")
        logger.info("="*80)
        raise