# whatsappcrm_backend/flows/whatsapp_flow_response_processor.py
"""
Service for processing WhatsApp Flow responses and updating the contact's
flow context. When a user completes a WhatsApp UI Flow, the response data
is merged into the active ContactFlowState so downstream conversational
flow steps can consume it.
"""

import logging
from typing import Dict, Any, Optional
from django.utils import timezone
from django.db import transaction
from .models import WhatsAppFlow, WhatsAppFlowResponse, ContactFlowState
from conversations.models import Contact

logger = logging.getLogger(__name__)


class WhatsAppFlowResponseProcessor:
    """
    Processes WhatsApp Flow responses and merges them into
    the active conversational flow context.
    """

    @staticmethod
    @transaction.atomic
    def process_response(
        whatsapp_flow: WhatsAppFlow,
        contact: Contact,
        response_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Updates the contact's flow context with WhatsApp flow response data.
        Called from the webhook handler when a flow response is received.

        Args:
            whatsapp_flow: The WhatsAppFlow instance
            contact: The contact who submitted the response
            response_data: The response payload from Meta
        Returns:
            Dict with status and notes, or None if failed
        """
        try:
            # Save the flow response for audit / history
            WhatsAppFlowResponse.objects.create(
                whatsapp_flow=whatsapp_flow,
                contact=contact,
                flow_token=response_data.get('flow_token', ''),
                response_data=response_data,
                is_processed=True,
                processed_at=timezone.now(),
            )
            logger.info(
                f"Saved WhatsAppFlowResponse for contact {contact.id} "
                f"and flow {whatsapp_flow.name}."
            )

            # Update the flow context for the contact (if in a flow)
            flow_state = (
                ContactFlowState.objects
                .select_for_update()
                .filter(contact=contact)
                .first()
            )

            if not flow_state:
                logger.warning(
                    f"No active flow state for contact {contact.id} "
                    "when processing WhatsApp flow response."
                )
                return {
                    "success": False,
                    "notes": "No active flow state for contact.",
                }

            # Merge WhatsApp flow data into the flow context
            context = flow_state.flow_context_data or {}
            wa_data = response_data.get('data', response_data)

            # Merge at top level for easy access by downstream steps
            context.update(wa_data)

            # Also keep under a subkey for backward compatibility
            context['whatsapp_flow_data'] = wa_data

            # Flag for transition conditions
            context['whatsapp_flow_response_received'] = True

            flow_state.flow_context_data = context
            flow_state.last_updated_at = timezone.now()
            flow_state.save(update_fields=["flow_context_data", "last_updated_at"])

            logger.info(
                f"Successfully updated flow context for contact {contact.id} "
                f"with WhatsApp flow data. Current step: {flow_state.current_step.name}"
            )

            return {
                "success": True,
                "notes": "Flow context updated with WhatsApp flow data.",
            }

        except Exception as e:
            logger.error(
                f"Error processing WhatsApp flow response for contact "
                f"{contact.id}: {e}",
                exc_info=True,
            )
            return None
