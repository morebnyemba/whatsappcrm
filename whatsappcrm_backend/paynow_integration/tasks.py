# paynow_integration/tasks.py
import logging
from celery import shared_task
from decimal import Decimal

from .services import PaynowService
from customer_data.models import WalletTransaction
from meta_integration.utils import send_whatsapp_message, create_text_message_data

logger = logging.getLogger(__name__)

@shared_task(name="paynow_integration.initiate_paynow_express_checkout_task", bind=True, max_retries=3, default_retry_delay=60)
def initiate_paynow_express_checkout_task(self, transaction_reference: str):
    """
    Asynchronously initiates a Paynow Express Checkout payment.
    This task is called after a PENDING WalletTransaction has been created.
    """
    logger.info(f"Celery task started: initiate_paynow_express_checkout_task for reference {transaction_reference}")
    try:
        # Find the pending transaction
        pending_tx = WalletTransaction.objects.get(reference=transaction_reference, status='PENDING')
        wallet = pending_tx.wallet
        profile = wallet.user.customer_profile
        contact = profile.contact
        
        # Extract necessary details from the transaction and related models
        amount = pending_tx.amount
        payment_details = pending_tx.payment_details
        phone_number = payment_details.get('phone_number')
        paynow_method_type = payment_details.get('paynow_method_type')
        email = profile.user.email if profile.user and profile.user.email else f"{contact.whatsapp_id}@example.com"

        if not all([phone_number, paynow_method_type]):
            raise ValueError("Phone number or Paynow method type missing in transaction payment_details.")

        paynow_service = PaynowService()
        paynow_response = paynow_service.initiate_express_checkout_payment(
            amount=amount,
            reference=transaction_reference,
            phone_number=phone_number,
            email=email,
            paynow_method_type=paynow_method_type,
            description=pending_tx.description
        )

        if paynow_response.get('success'):
            pending_tx.external_reference = paynow_response.get('paynow_reference')
            pending_tx.save(update_fields=['external_reference'])
            
            instructions = paynow_response.get('instructions', 'Please check your phone to approve the payment.')
            message_body = (
                f"Your Paynow deposit has been initiated.\n\n"
                f"{instructions}\n\n"
                f"We will notify you once the payment is confirmed."
            )
            message_data = create_text_message_data(text_body=message_body)
            send_whatsapp_message(to_phone_number=contact.whatsapp_id, message_type='text', data=message_data)
            logger.info(f"Successfully initiated Paynow payment for {transaction_reference} and sent instructions to {contact.whatsapp_id}.")
        else:
            raise Exception(paynow_response.get('message', 'Unknown error from Paynow'))

    except WalletTransaction.DoesNotExist:
        logger.error(f"Task failed: WalletTransaction with reference {transaction_reference} not found.")
    except Exception as e:
        logger.error(f"Error in initiate_paynow_express_checkout_task for ref {transaction_reference}: {e}", exc_info=True)
        try:
            # Mark transaction as failed and notify user
            tx_to_fail = WalletTransaction.objects.get(reference=transaction_reference)
            tx_to_fail.status = 'FAILED'
            tx_to_fail.description = f"Payment initiation failed: {str(e)[:200]}"
            tx_to_fail.save()
            
            contact_to_notify = tx_to_fail.wallet.user.customer_profile.contact
            failure_message = f"❌ We're sorry, but we could not initiate your payment at this time. Reason: {str(e)[:100]}. Please try again later."
            message_data = create_text_message_data(text_body=failure_message)
            send_whatsapp_message(to_phone_number=contact_to_notify.whatsapp_id, message_type='text', data=message_data)
        except Exception as notify_err:
            logger.error(f"Failed to notify user about payment initiation failure for ref {transaction_reference}: {notify_err}")
        self.retry(exc=e)