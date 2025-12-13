# whatsappcrm_backend/flows/tasks.py

import logging
from datetime import timedelta
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from conversations.models import Message, Contact
from meta_integration.models import MetaAppConfig
from meta_integration.tasks import send_whatsapp_message_task
from .services import process_message_for_flow, _clear_contact_flow_state
from .models import ContactFlowState

logger = logging.getLogger(__name__)


@shared_task(queue='celery', priority=9)  # High priority for instant message processing
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
            try:
                config_to_use = MetaAppConfig.objects.get_active_config()
            except MetaAppConfig.DoesNotExist:
                logger.error(f"No active MetaAppConfig found. Cannot send flow responses for message {message_id}.")
                return
            except MetaAppConfig.MultipleObjectsReturned:
                logger.error(f"Multiple active MetaAppConfig found. Cannot determine which to use for message {message_id}.")
                return

            if not config_to_use:
                logger.error(f"No active MetaAppConfig found. Cannot send flow responses for message {message_id}.")
                return

            dispatch_countdown = 0
            for action in actions_to_perform:
                if action.get('type') == 'send_whatsapp_message':
                    recipient_wa_id = action.get('recipient_wa_id', contact.whatsapp_id)
                    
                    # Use the service to get or create recipient contact
                    from conversations.services import get_or_create_contact_by_wa_id
                    recipient_contact, _ = get_or_create_contact_by_wa_id(
                        wa_id=recipient_wa_id,
                        name='Unknown'
                    )
                    
                    if not recipient_contact:
                        logger.error(f"Failed to get/create recipient contact for {recipient_wa_id}")
                        continue

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


@shared_task(name="flows.cleanup_idle_conversations_task")
def cleanup_idle_conversations_task():
    """
    Finds and cleans up idle conversations (flow mode) that have
    been inactive for more than 5 minutes (matching reference repo best practices).
    """
    idle_threshold = timezone.now() - timedelta(minutes=5)
    log_prefix = "[Idle Conversation Cleanup]"
    logger.info(f"{log_prefix} Running task for conversations idle since before {idle_threshold}.")

    # Find idle contacts in flows
    # A contact is idle in a flow if their flow state hasn't been updated recently.
    idle_flow_states = ContactFlowState.objects.filter(
        last_updated_at__lt=idle_threshold
    ).select_related('contact', 'current_flow')

    timed_out_contacts = set()

    # Process idle flow contacts
    for state in idle_flow_states:
        contact = state.contact
        logger.info(
            f"{log_prefix} Clearing idle flow '{state.current_flow.name}' for contact "
            f"{contact.id} ({contact.whatsapp_id}). Last activity: {state.last_updated_at}"
        )
        _clear_contact_flow_state(contact)
        timed_out_contacts.add(contact)

    # Send notifications to timed out contacts
    if timed_out_contacts:
        logger.info(f"{log_prefix} Sending timeout notifications to {len(timed_out_contacts)} contacts.")
        try:
            config_to_use = MetaAppConfig.objects.get_active_config()
            notification_text = "Your session has expired due to inactivity. Please send 'menu' to start over."
            
            for contact in timed_out_contacts:
                outgoing_msg = Message.objects.create(
                    contact=contact,
                    direction='out',
                    message_type='text',
                    content_payload={'body': notification_text},
                    status='pending_dispatch'
                )
                send_whatsapp_message_task.delay(outgoing_msg.id, config_to_use.id)
        except MetaAppConfig.DoesNotExist:
            logger.error(f"{log_prefix} No active MetaAppConfig found. Cannot send timeout notifications.")
        except Exception as e:
            logger.error(f"{log_prefix} Error sending timeout notifications: {e}", exc_info=True)

    logger.info(f"{log_prefix} Cleanup complete. Timed out {len(timed_out_contacts)} contacts.")

