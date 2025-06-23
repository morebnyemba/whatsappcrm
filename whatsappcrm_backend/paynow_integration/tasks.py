# paynow_integration/tasks.py
import logging
import time
from celery import shared_task
from decimal import Decimal
import requests
from django.db import transaction

from .services import PaynowService
from customer_data.models import WalletTransaction, UserWallet

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

            # Schedule the polling task
            poll_paynow_transaction_status.delay(transaction_reference=transaction_reference)
            logger.info(f"Successfully initiated Paynow payment for {transaction_reference} and scheduled polling.")
        else:
            raise Exception(paynow_response.get('message', 'Unknown error from Paynow'))

    except WalletTransaction.DoesNotExist:
        logger.error(f"Task failed: WalletTransaction with reference {transaction_reference} not found.")
    except Exception as e: # Catch Paynow initiation failure
        logger.error(f"Error initiating Paynow for {transaction_reference}: {e}", exc_info=True)
        fail_pending_transaction_and_notify.delay(transaction_reference=transaction_reference, error_message=str(e)[:200]) # Notify immediately

@shared_task(name="paynow_integration.poll_paynow_transaction_status", bind=True, max_retries=10, default_retry_delay=120)
def poll_paynow_transaction_status(self, transaction_reference: str):
    """
    Polls Paynow to get the transaction status and updates the WalletTransaction accordingly.
    """
    logger.info(f"Polling Paynow status for transaction reference: {transaction_reference}")
    try:
        pending_tx = WalletTransaction.objects.get(reference=transaction_reference, status='PENDING')
        paynow_service = PaynowService()
        
        # Get the status from Paynow
        status_response = paynow_service.get_express_checkout_status(pending_tx.external_reference)
        
        if status_response['success']:
            status = status_response['status']
            logger.info(f"Paynow status for {transaction_reference}: {status}")

            if status.lower() == 'paid':
                # --- BUG FIX: Update existing transaction instead of creating a new one ---
                wallet = pending_tx.wallet
                with transaction.atomic(): # Atomic transaction to prevent race conditions
                    # Lock the wallet row to prevent race conditions while updating balance
                    wallet_to_update = UserWallet.objects.select_for_update().get(pk=wallet.pk)
                    wallet_to_update.balance += pending_tx.amount
                    wallet_to_update.save(update_fields=['balance', 'updated_at'])

                    # Now, update the original transaction to completed
                    pending_tx.status = 'COMPLETED'
                    pending_tx.description = f"Paynow deposit successful. Paynow Ref: {pending_tx.external_reference}"
                    pending_tx.save(update_fields=['status', 'description'])
                logger.info(f"Successfully processed deposit for Ref {transaction_reference}. User: {wallet.user.username}, Amount: {pending_tx.amount}. New balance: {wallet.balance}")
                wallet.refresh_from_db()  # Refresh the wallet object to get the latest balance for the notification
                
                # Send success notification
                send_deposit_confirmation_whatsapp.delay(
                    whatsapp_id=wallet.user.customer_profile.contact.whatsapp_id,
                    amount=str(pending_tx.amount),
                    new_balance=str(wallet.balance),
                    transaction_reference=transaction_reference,
                    currency_symbol="$"
                )

            elif status.lower() in ['cancelled', 'failed']:
                pending_tx.status = 'FAILED'
                pending_tx.description = f"Paynow transaction failed. Status: {status}"
                pending_tx.save()
                logger.warning(f"Paynow transaction failed for Ref {transaction_reference}. Status: {status}")
                fail_pending_transaction_and_notify.delay(transaction_reference=transaction_reference, error_message=f"Paynow payment failed with status: {status}")
            else:
                # Status is still pending, retry the task
                logger.info(f"Transaction {transaction_reference} is still pending. Retrying...")
                self.retry(exc=Exception(f"Transaction is still pending.  Current status: {status}"))
        else:
            logger.error(f"Failed to get Paynow status for {transaction_reference}: {status_response.get('message')}")
            self.retry(exc=Exception(f"Failed to get Paynow status: {status_response.get('message')}"))

    except WalletTransaction.DoesNotExist:
        logger.error(f"Transaction with reference {transaction_reference} not found during polling.")
    except Exception as e:
        logger.error(f"Error polling Paynow for {transaction_reference}: {e}", exc_info=True)
        self.retry(exc=e)


@shared_task(name="paynow_integration.fail_pending_transaction_and_notify")
def fail_pending_transaction_and_notify(transaction_reference: str, error_message: str):
    """
    Marks a pending transaction as failed and sends a WhatsApp notification to the user.
    """
    logger.info(f"Marking transaction {transaction_reference} as failed and notifying user.")
    try:
        tx_to_fail = WalletTransaction.objects.get(reference=transaction_reference, status='PENDING')
        tx_to_fail.status = 'FAILED'
        tx_to_fail.description = f"Payment failed: {error_message}"
        tx_to_fail.save()

        contact_to_notify = tx_to_fail.wallet.user.customer_profile.contact
        failure_message = f"❌ We're sorry, but your payment could not be processed. Reason: {error_message}. Please try again later."
        message_data = create_text_message_data(text_body=failure_message)
        send_whatsapp_message(to_phone_number=contact_to_notify.whatsapp_id, message_type='text', data=message_data)
        logger.info(f"Successfully notified user {contact_to_notify.whatsapp_id} about payment failure for {transaction_reference}.")
    except WalletTransaction.DoesNotExist:
        logger.error(f"Transaction with reference {transaction_reference} not found while attempting to mark as failed.")
    except Exception as e:
        logger.error(f"Error marking transaction {transaction_reference} as failed and notifying user: {e}", exc_info=True)

from meta_integration.utils import send_whatsapp_message, create_text_message_data #Import here to avoid circular dependency
from customer_data.tasks import send_deposit_confirmation_whatsapp