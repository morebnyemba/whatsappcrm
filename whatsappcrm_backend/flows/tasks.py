# whatsappcrm_backend/flows/tasks.py

import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from conversations.models import Message, Contact
from meta_integration.models import MetaAppConfig
from meta_integration.tasks import send_whatsapp_message_task
from .services import process_message_for_flow

logger = logging.getLogger(__name__)


@shared_task(queue='celery')  # Use your main I/O queue
def process_flow_for_message_task(message_id: int):
    """
    This task asynchronously runs the entire flow engine for an incoming message.
    
    Args:
        message_id: ID of the incoming Message object to process
    """
    try:
        with transaction.atomic():
            incoming_message = Message.objects.select_related('contact').get(pk=message_id)
            contact = incoming_message.contact
            message_data = incoming_message.content_payload or {}

            logger.info(f"Processing flow for message {message_id} from contact {contact.whatsapp_id}")

            actions_to_perform = process_message_for_flow(contact, message_data, incoming_message)

            if not actions_to_perform:
                logger.info(f"Flow processing for message {message_id} resulted in no actions.")
                return

            # Determine which config to use for sending responses
            config_to_use = MetaAppConfig.objects.get_active_config()

            if not config_to_use:
                logger.error(f"No active MetaAppConfig found. Cannot send flow responses for message {message_id}.")
                return

            dispatch_countdown = 0
            for action in actions_to_perform:
                if action.get('type') == 'send_whatsapp_message':
                    recipient_wa_id = action.get('recipient_wa_id', contact.whatsapp_id)
                    
                    # Get or create recipient contact
                    recipient_contact, _ = Contact.objects.get_or_create(
                        whatsapp_id=recipient_wa_id,
                        defaults={'name': 'Unknown'}
                    )

                    # Create outgoing message
                    outgoing_msg = Message.objects.create(
                        contact=recipient_contact,
                        direction='out',
                        message_type=action.get('message_type'),
                        content_payload=action.get('data'),
                        status='pending_dispatch',
                        timestamp=timezone.now(),
                        triggered_by_flow_step_id=getattr(getattr(contact, 'flow_state', None), 'current_step_id', None)
                    )

                    # Queue the send task with a countdown to ensure sequential delivery
                    send_whatsapp_message_task.apply_async(
                        args=[outgoing_msg.id, config_to_use.id],
                        countdown=dispatch_countdown
                    )
                    logger.info(f"Queued message {outgoing_msg.id} for sending to {recipient_wa_id} with {dispatch_countdown}s delay")
                    dispatch_countdown += 2  # Add 2 seconds between messages

    except Message.DoesNotExist:
        logger.error(f"process_flow_for_message_task: Message with ID {message_id} not found.")
    except Exception as e:
        logger.error(f"Critical error in process_flow_for_message_task for message {message_id}: {e}", exc_info=True)
