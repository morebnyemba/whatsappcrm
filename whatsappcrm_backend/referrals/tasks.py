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
    try:
        user = User.objects.select_related('customer_profile__contact').get(id=user_id)
        whatsapp_id = user.customer_profile.contact.whatsapp_id
        
        if not whatsapp_id:
            logger.warning(f"Cannot send bonus notification to user {user_id}. No WhatsApp ID found.")
            return

        message_data = create_text_message_data(text_body=message)
        send_whatsapp_message(to_phone_number=whatsapp_id, message_type='text', data=message_data)
        logger.info(f"Successfully sent bonus notification to user {user_id} ({whatsapp_id}).")
    except User.DoesNotExist:
        logger.error(f"User with ID {user_id} not found for sending bonus notification.")
    except Exception as e:
        logger.error(f"Error in send_bonus_notification_task for user {user_id}: {e}", exc_info=True)
        raise