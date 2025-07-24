# paynow_integration/tasks.py
import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .services import PaynowService
from meta_integration.utils import send_whatsapp_message, create_text_message_data
from customer_data.models import WalletTransaction, UserWallet
from customer_data.tasks import send_deposit_confirmation_whatsapp

logger = logging.getLogger(__name__)

def _fail_transaction_and_notify_user(transaction_obj: WalletTransaction, reason: str):
    """
    Internal helper to mark a transaction as FAILED and notify the user.
    This is not a Celery task itself but a utility function.
    """
    logger.warning(f"Attempting to fail transaction {transaction_obj.reference}. Reason: {reason}")

    tx_to_fail = None
    try:
        with transaction.atomic():
            # Atomically fetch and lock the transaction ONLY if it's still PENDING.
            # This prevents a race condition where an IPN completes the transaction
            # just before this function tries to fail it.
            tx_to_fail = WalletTransaction.objects.select_for_update().get(
                pk=transaction_obj.pk,
                status='PENDING'
            )
            
            tx_to_fail.status = 'FAILED'
            tx_to_fail.description = reason[:255] # Truncate reason to fit model field
            tx_to_fail.save(update_fields=['status', 'description'])
            
    except WalletTransaction.DoesNotExist:
        # This is not an error. It means the transaction was already processed
        # (e.g., COMPLETED by an IPN) between when the fail task was called
        # and when this lock was acquired.
        logger.info(
            f"Transaction {transaction_obj.reference} was not in PENDING state "
            f"when attempting to fail it. It was likely already processed. No action taken."
        )
        return # Exit without doing anything further

    # If we successfully failed the transaction, now notify the user.
    # This is outside the atomic block to avoid holding locks during network calls.
    if tx_to_fail:
        try:
            contact_to_notify = tx_to_fail.wallet.user.customer_profile.contact
            failure_message = f"❌ We're sorry, but your payment could not be processed. Please try again later. (Ref: {tx_to_fail.reference})"
            message_data = create_text_message_data(text_body=failure_message)
            send_whatsapp_message(to_phone_number=contact_to_notify.whatsapp_id, message_type='text', data=message_data)
            logger.info(f"Successfully notified user {contact_to_notify.whatsapp_id} about payment failure for {tx_to_fail.reference}.")
        except Exception as notify_exc:
            logger.error(f"Error notifying user about failed transaction {tx_to_fail.reference}: {notify_exc}", exc_info=True)

@shared_task(name="paynow_integration.initiate_paynow_express_checkout_task", bind=True, max_retries=3, default_retry_delay=90)
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
            
            # Always store the poll_url if provided by Paynow
            if paynow_response.get('poll_url'):
                pending_tx.payment_details['poll_url'] = paynow_response.get('poll_url')

            # --- Specific handling for different payment methods ---
            if paynow_method_type == 'omari':
                otpreference = paynow_response.get('otpreference')
                remoteotpurl = paynow_response.get('remoteotpurl')
                if not otpreference or not remoteotpurl:
                    raise Exception("O'mari payment initiated but missing OTP reference or remote OTP URL.")
                pending_tx.payment_details['otpreference'] = otpreference
                pending_tx.payment_details['remoteotpurl'] = remoteotpurl
                pending_tx.save(update_fields=['external_reference', 'payment_details'])
                logger.info(f"O'mari payment initiated for {transaction_reference}. OTP required. Not scheduling polling yet.")
                # The flow will need to ask for OTP, then a new action/task will submit it.
                # Polling will only start after successful OTP submission.
            elif paynow_method_type == 'innbucks':
                authorizationcode = paynow_response.get('authorizationcode')
                authorizationexpires = paynow_response.get('authorizationexpires')
                if authorizationcode:
                    pending_tx.payment_details['authorizationcode'] = authorizationcode
                    pending_tx.payment_details['authorizationexpires'] = authorizationexpires
                pending_tx.save(update_fields=['external_reference', 'payment_details'])
                
                # Schedule sending the specific InnBucks message
                send_innbucks_authorization_message.delay(transaction_reference=transaction_reference)
                poll_paynow_transaction_status.delay(transaction_reference=transaction_reference)
                logger.info(f"InnBucks payment initiated for {transaction_reference}. Authorization code: {authorizationcode}. Polling scheduled.")
            else: # Default for EcoCash and other direct mobile money methods
                pending_tx.save(update_fields=['external_reference', 'payment_details'])
                poll_paynow_transaction_status.delay(transaction_reference=transaction_reference)
                logger.info(f"Successfully initiated Paynow payment for {transaction_reference} and scheduled polling.")
        else:
            raise Exception(paynow_response.get('message', 'Unknown error from Paynow'))
    
    except (WalletTransaction.DoesNotExist, ValueError) as e:
        # These are permanent, non-recoverable errors. Do not retry.
        logger.error(f"Permanent error initiating Paynow for {transaction_reference}, will not retry: {e}", exc_info=True)
        fail_pending_transaction_and_notify.delay(transaction_reference=transaction_reference, error_message=str(e)[:200])
    except Exception as e:
        # These are potentially transient errors (e.g., network timeout, Paynow 500 error).
        logger.warning(f"Transient error initiating Paynow for {transaction_reference}, will retry ({self.request.retries + 1}/{self.max_retries}): {e}")
        try:
            # Retry the task with the default delay.
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for initiating payment {transaction_reference}. Failing transaction.")
            fail_pending_transaction_and_notify.delay(transaction_reference=transaction_reference, error_message=f"Failed after multiple retries: {str(e)[:150]}")

@shared_task(name="paynow_integration.poll_paynow_transaction_status", bind=True, max_retries=10, default_retry_delay=120)
def poll_paynow_transaction_status(self, transaction_reference: str):
    """
    Polls Paynow to get the transaction status and updates the WalletTransaction accordingly.
    """
    logger.info(f"Polling Paynow status for transaction reference: {transaction_reference}")
    # Use a transaction.atomic block to ensure the initial get-and-lock is atomic.
    try:
        with transaction.atomic():
            # FIX: Lock the WalletTransaction row to prevent race conditions.
            # If a second task tries this, it will wait. When it gets the lock,
            # the status will no longer be 'PENDING', and it will raise DoesNotExist.
            pending_tx = WalletTransaction.objects.select_for_update().get(reference=transaction_reference, status='PENDING')
            
            paynow_service = PaynowService()
            poll_url = pending_tx.payment_details.get('poll_url')
            if not poll_url:
                logger.error(f"Poll URL not found for transaction {transaction_reference}. Failing transaction.")
                _fail_transaction_and_notify_user(pending_tx, "Could not poll status: Poll URL missing.")
                return # Stop execution

            status_response = paynow_service.check_transaction_status(poll_url)
            
            if status_response['success']:
                status = status_response['status']
                logger.info(f"Paynow status for {transaction_reference}: {status}")

                if status.lower() == 'paid':
                    wallet = pending_tx.wallet
                    # This second lock is good for protecting the wallet from other simultaneous operations.
                    wallet_to_update = UserWallet.objects.select_for_update().get(pk=wallet.pk)
                    wallet_to_update.balance += pending_tx.amount
                    wallet_to_update.save(update_fields=['balance', 'updated_at'])

                    pending_tx.status = 'COMPLETED'
                    pending_tx.description = f"Paynow deposit successful. Paynow Ref: {pending_tx.external_reference}"
                    pending_tx.save(update_fields=['status', 'description', 'updated_at'])
                    
                    wallet.refresh_from_db()
                    logger.info(f"Successfully processed deposit for Ref {transaction_reference}. User: {wallet.user.username}, Amount: {pending_tx.amount}. New balance: {wallet.balance}")
                    
                    send_deposit_confirmation_whatsapp.delay(
                        whatsapp_id=wallet.user.customer_profile.contact.whatsapp_id,
                        amount=str(pending_tx.amount),
                        new_balance=f"{wallet.balance:.2f}",
                        transaction_reference=transaction_reference,
                        currency_symbol="$"
                    )
                    return # Task is complete

                elif status.lower() in ['cancelled', 'failed', 'disputed']:
                    reason = f"Paynow transaction status was '{status}'."
                    _fail_transaction_and_notify_user(pending_tx, reason)
                    return # Task is complete

                else: # 'pending', 'created', etc.
                    logger.info(f"Transaction {transaction_reference} is still pending. Retrying...")
                    self.retry(exc=Exception(f"Transaction is still pending. Current status: {status}"))
            else:
                logger.error(f"Failed to get Paynow status for {transaction_reference}: {status_response.get('message')}")
                self.retry(exc=Exception(f"Failed to get Paynow status: {status_response.get('message')}"))

    except WalletTransaction.DoesNotExist:
        # This is now an expected, non-error outcome for a concurrent task.
        logger.info(f"Transaction {transaction_reference} not found or not PENDING. It was likely processed by another task. Stopping poll.")
    except Exception as e:
        logger.error(f"Error polling Paynow for {transaction_reference}: {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for polling transaction {transaction_reference}. Attempting to fail it.")
            try:
                tx_to_fail = WalletTransaction.objects.get(reference=transaction_reference, status='PENDING')
                _fail_transaction_and_notify_user(tx_to_fail, f"Polling failed after max retries: {str(e)[:100]}")
            except WalletTransaction.DoesNotExist:
                logger.warning(f"Could not find transaction {transaction_reference} to fail after max retries (it might have been processed or failed already).")
            except Exception as final_fail_exc:
                logger.critical(f"Could not fail transaction {transaction_reference} after max retries: {final_fail_exc}")

@shared_task(name="paynow_integration.send_innbucks_authorization_message")
def send_innbucks_authorization_message(transaction_reference: str):
    """
    Sends a WhatsApp message to the user with InnBucks authorization details.
    """
    logger.info(f"Preparing to send InnBucks authorization message for transaction {transaction_reference}")
    try:
        transaction_obj = WalletTransaction.objects.get(reference=transaction_reference)
        
        authorization_code = transaction_obj.payment_details.get('authorizationcode')
        authorization_expires = transaction_obj.payment_details.get('authorizationexpires')
        whatsapp_id = transaction_obj.wallet.user.customer_profile.contact.whatsapp_id

        if not authorization_code:
            logger.error(f"InnBucks authorization code not found for transaction {transaction_reference}. Cannot send message.")
            return

        message_body = (
            f"Your InnBucks deposit for ${transaction_obj.amount:.2f} has been initiated.\n\n"
            f"Please use the following authorization code to complete your payment in the InnBucks app:\n"
            f"*{authorization_code}*\n\n"
            f"This code expires on: {authorization_expires}\n\n"
            f"You can also use this deep link to open the InnBucks app directly (if installed):\n"
            f"schinn.wbpycode://innbucks.co.zw?pymInnCode={authorization_code}\n\n"
            f"We will notify you once your deposit is confirmed."
        )
        
        message_data = create_text_message_data(text_body=message_body)
        send_whatsapp_message(to_phone_number=whatsapp_id, message_type='text', data=message_data)
        logger.info(f"Successfully sent InnBucks authorization message for transaction {transaction_reference} to {whatsapp_id}.")

    except WalletTransaction.DoesNotExist:
        logger.error(f"WalletTransaction {transaction_reference} not found for InnBucks authorization message.")
    except Exception as e:
        logger.error(f"Error sending InnBucks authorization message for {transaction_reference}: {e}", exc_info=True)


@shared_task(name="paynow_integration.fail_pending_transaction_and_notify")
def fail_pending_transaction_and_notify(transaction_reference: str, error_message: str):
    """
    Marks a PENDING transaction as failed and sends a WhatsApp notification to the user.
    This is primarily for immediate failures during initiation, not for polling results.
    """
    logger.info(f"Task to fail transaction {transaction_reference} and notify user.")
    try:
        tx_to_fail = WalletTransaction.objects.get(reference=transaction_reference, status='PENDING')
        reason = f"Payment initiation failed: {error_message}"
        _fail_transaction_and_notify_user(tx_to_fail, reason)
    except WalletTransaction.DoesNotExist:
        logger.error(f"Transaction with reference {transaction_reference} not found (or not PENDING) while attempting to mark as failed.")
    except Exception as e:
        logger.error(f"Error in fail_pending_transaction_and_notify task for {transaction_reference}: {e}", exc_info=True)