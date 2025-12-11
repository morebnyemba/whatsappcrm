# paynow_integration/tasks.py
import logging
from typing import Optional
from celery import shared_task
import random
from django.db import transaction
from django.utils import timezone

from .services import PaynowService
from meta_integration.utils import send_whatsapp_message, create_text_message_data
from customer_data.models import WalletTransaction, UserWallet
from customer_data.tasks import send_deposit_confirmation_whatsapp

logger = logging.getLogger(__name__)

def _fail_transaction_in_db(transaction_obj: WalletTransaction, reason: str) -> Optional[WalletTransaction]:
    """
    Internal helper to mark a transaction as FAILED in the database.
    This is NOT a Celery task. It returns the failed transaction on success, or None.
    """
    log_prefix = f"[DB Fail Helper - Ref: {transaction_obj.reference}]"
    logger.warning(f"{log_prefix} Attempting to fail transaction in DB. Reason: {reason}")

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
            tx_to_fail.save(update_fields=['status', 'description', 'updated_at'])
            logger.info(f"{log_prefix} Successfully marked transaction as FAILED in the database.")
            
    except WalletTransaction.DoesNotExist:
        # This is not an error. It means the transaction was already processed
        # (e.g., COMPLETED by an IPN) between when the fail task was called
        # and when this lock was acquired.
        logger.info(
            f"{log_prefix} Transaction was not in PENDING state "
            "when attempting to fail. It was likely already processed. No action taken."
        )
        return None

    return tx_to_fail

def _fail_transaction_and_notify_user(transaction_obj: WalletTransaction, reason: str):
    """
    Internal helper to fail a transaction in the DB and notify the user.
    This is NOT a Celery task.
    """
    log_prefix = f"[Fail & Notify Helper - Ref: {transaction_obj.reference}]"
    logger.info(f"{log_prefix} Starting process to fail transaction and notify user. Reason: {reason}")
    
    # First, try to fail the transaction in the database.
    # _fail_transaction_in_db is atomic and handles race conditions.
    # It returns the failed transaction object if it successfully marked it as FAILED,
    # or None if the transaction was already processed.
    failed_tx = _fail_transaction_in_db(transaction_obj, reason)
    
    # Only send a notification if the transaction was actually marked as FAILED by this process.
    if failed_tx:
        logger.info(f"{log_prefix} Transaction successfully failed. Triggering user notification.")
        send_payment_failure_notification_task.delay(transaction_reference=failed_tx.reference)
    else:
        logger.info(f"{log_prefix} Transaction was not failed by this process (likely already processed). No notification will be sent.")

@shared_task(name="paynow_integration.send_payment_failure_notification_task")
def send_payment_failure_notification_task(transaction_reference: str):
    """
    Sends a WhatsApp message to the user notifying them of a failed transaction.
    """
    log_prefix = f"[Failure Notif Task - Ref: {transaction_reference}]"
    logger.info(f"{log_prefix} Preparing to send failure notification.")
    try:
        # We don't need to lock here, just read the data.
        tx = WalletTransaction.objects.get(reference=transaction_reference)
        contact_to_notify = tx.wallet.user.customer_profile.contact
        
        failure_message = f"❌ We're sorry, but your payment could not be processed. Please try again later. (Ref: {tx.reference})"
        message_data = create_text_message_data(text_body=failure_message)
        send_whatsapp_message(to_phone_number=contact_to_notify.whatsapp_id, message_type='text', data=message_data)
        logger.info(f"{log_prefix} Successfully sent failure notification to user {contact_to_notify.whatsapp_id}.")
    except WalletTransaction.DoesNotExist:
        logger.error(f"{log_prefix} Could not find transaction to send failure notification.")
    except Exception as e:
        logger.error(f"{log_prefix} Error sending failure notification: {e}", exc_info=True)

@shared_task(name="paynow_integration.initiate_paynow_express_checkout_task", bind=True, max_retries=3, default_retry_delay=90)
def initiate_paynow_express_checkout_task(self, transaction_reference: str):
    """
    Asynchronously initiates a Paynow Express Checkout payment.
    This task is called after a PENDING WalletTransaction has been created.
    """
    logger.info("="*80)
    logger.info(f"TASK START: initiate_paynow_express_checkout_task")
    logger.info(f"Transaction Ref: {transaction_reference}")
    logger.info(f"Task ID: {self.request.id}, Retry: {self.request.retries}/{self.max_retries}")
    logger.info("="*80)
    
    log_prefix = f"[Initiate - Ref: {transaction_reference}]"
    
    try:
        # Find the pending transaction
        logger.debug(f"{log_prefix} Fetching transaction from database...")
        pending_tx = WalletTransaction.objects.get(reference=transaction_reference, status='PENDING')
        wallet = pending_tx.wallet
        profile = wallet.user.customer_profile
        contact = profile.contact
        
        logger.info(f"{log_prefix} Transaction found - User: {wallet.user.username}, Amount: ${pending_tx.amount}")

        # Extract necessary details from the transaction and related models
        amount = pending_tx.amount
        payment_details = pending_tx.payment_details
        phone_number = payment_details.get('phone_number')
        paynow_method_type = payment_details.get('paynow_method_type')
        email = profile.user.email if profile.user and profile.user.email else f"{contact.whatsapp_id}@example.com"

        if not all([phone_number, paynow_method_type]):
            raise ValueError("Phone number or Paynow method type missing in transaction payment_details.")

        logger.info(f"{log_prefix} Initiating Paynow payment: Amount=${amount}, Method={paynow_method_type}, Phone={phone_number}")

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
            paynow_ref = paynow_response.get('paynow_reference')
            pending_tx.external_reference = paynow_ref
            logger.info(f"{log_prefix} ✓ Paynow payment initiated successfully. Paynow Ref: {paynow_ref}")
            
            # Always store the poll_url if provided by Paynow
            if paynow_response.get('poll_url'):
                pending_tx.payment_details['poll_url'] = paynow_response.get('poll_url')
                logger.debug(f"{log_prefix} Stored poll_url")

            # --- Specific handling for different payment methods ---
            if paynow_method_type == 'omari':
                otpreference = paynow_response.get('otpreference')
                remoteotpurl = paynow_response.get('remoteotpurl')
                if not otpreference or not remoteotpurl:
                    raise Exception("O'mari payment initiated but missing OTP reference or remote OTP URL.")
                pending_tx.payment_details['otpreference'] = otpreference
                pending_tx.payment_details['remoteotpurl'] = remoteotpurl
                pending_tx.save(update_fields=['external_reference', 'payment_details'])
                logger.info(f"{log_prefix} O'mari method - OTP required. Not scheduling polling yet.")
                logger.info("="*80)
                logger.info(f"TASK END: initiate_paynow_express_checkout_task - SUCCESS (O'mari - awaiting OTP)")
                logger.info("="*80)
                # The flow will need to ask for OTP, then a new action/task will submit it.
                # Polling will only start after successful OTP submission.
            elif paynow_method_type == 'innbucks':
                authorizationcode = paynow_response.get('authorizationcode')
                authorizationexpires = paynow_response.get('authorizationexpires')
                if authorizationcode:
                    pending_tx.payment_details['authorizationcode'] = authorizationcode
                    pending_tx.payment_details['authorizationexpires'] = authorizationexpires
                pending_tx.save(update_fields=['external_reference', 'payment_details'])
                
                logger.info(f"{log_prefix} InnBucks method - Authorization code: {authorizationcode}")
                logger.info(f"{log_prefix} Scheduling InnBucks notification and polling tasks...")
                # Schedule sending the specific InnBucks message
                send_innbucks_authorization_message.delay(transaction_reference=transaction_reference)
                poll_paynow_transaction_status.delay(transaction_reference=transaction_reference)
                logger.info(f"{log_prefix} InnBucks tasks scheduled successfully")
                logger.info("="*80)
                logger.info(f"TASK END: initiate_paynow_express_checkout_task - SUCCESS (InnBucks)")
                logger.info("="*80)
            else: # Default for EcoCash and other direct mobile money methods
                pending_tx.save(update_fields=['external_reference', 'payment_details'])
                logger.info(f"{log_prefix} Method: {paynow_method_type} - Scheduling polling task...")
                poll_paynow_transaction_status.delay(transaction_reference=transaction_reference)
                logger.info(f"{log_prefix} Polling task scheduled successfully")
                logger.info("="*80)
                logger.info(f"TASK END: initiate_paynow_express_checkout_task - SUCCESS")
                logger.info("="*80)
        else:
            error_msg = paynow_response.get('message', 'Unknown error from Paynow')
            logger.error(f"{log_prefix} ✗ Paynow API returned failure: {error_msg}")
            raise Exception(error_msg)
    
    except (WalletTransaction.DoesNotExist, ValueError) as e:
        # These are permanent, non-recoverable errors. Do not retry.
        logger.error(f"{log_prefix} PERMANENT ERROR - Will not retry: {e}", exc_info=True)
        logger.info("="*80)
        logger.info(f"TASK END: initiate_paynow_express_checkout_task - FAILED (Permanent error)")
        logger.info("="*80)
    except Exception as e:
        # These are potentially transient errors (e.g., network timeout, Paynow 500 error).
        logger.warning(f"{log_prefix} TRANSIENT ERROR - Retry {self.request.retries + 1}/{self.max_retries}: {e}")
        try:
            # Retry the task with the default delay.
            logger.info(f"{log_prefix} Scheduling retry in {self.default_retry_delay}s...")
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"{log_prefix} Max retries exceeded. Marking transaction as failed.")
            fail_pending_transaction_and_notify.delay(transaction_reference=transaction_reference, error_message=f"Failed after multiple retries: {str(e)[:150]}")
            logger.info("="*80)
            logger.info(f"TASK END: initiate_paynow_express_checkout_task - FAILED (Max retries exceeded)")
            logger.info("="*80)

@shared_task(name="paynow_integration.poll_paynow_transaction_status", bind=True, max_retries=10, default_retry_delay=120)
def poll_paynow_transaction_status(self, transaction_reference: str):
    """
    Polls Paynow to get the transaction status and updates the WalletTransaction accordingly.
    """
    logger.info("="*80)
    logger.info(f"TASK START: poll_paynow_transaction_status")
    logger.info(f"Transaction Ref: {transaction_reference}")
    logger.info(f"Task ID: {self.request.id}, Poll Attempt: {self.request.retries + 1}/{self.max_retries + 1}")
    logger.info("="*80)
    
    log_prefix = f"[Poll - Ref: {transaction_reference}]"
    
    # Use a transaction.atomic block to ensure the initial get-and-lock is atomic.
    try:
        with transaction.atomic():
            # FIX: Lock the WalletTransaction row to prevent race conditions.
            # If a second task tries this, it will wait. When it gets the lock,
            # the status will no longer be 'PENDING', and it will raise DoesNotExist.
            logger.debug(f"{log_prefix} Acquiring database lock on transaction...")
            pending_tx = WalletTransaction.objects.select_for_update().get(reference=transaction_reference, status='PENDING')
            
            logger.info(f"{log_prefix} Transaction locked - User: {pending_tx.wallet.user.username}, Amount: ${pending_tx.amount}")
            
            paynow_service = PaynowService()
            poll_url = pending_tx.payment_details.get('poll_url')
            if not poll_url:
                logger.error(f"{log_prefix} Poll URL not found in payment_details. Cannot poll status.")
                _fail_transaction_and_notify_user(pending_tx, "Could not poll status: Poll URL missing.")
                logger.info("="*80)
                logger.info(f"TASK END: poll_paynow_transaction_status - FAILED (No poll URL)")
                logger.info("="*80)
                return # Stop execution

            logger.info(f"{log_prefix} Calling Paynow API to check transaction status...")
            status_response = paynow_service.check_transaction_status(poll_url)
            
            if status_response['success']:
                status = status_response['status']
                logger.info(f"{log_prefix} Paynow API response - Status: '{status}'")

                if status.lower() == 'paid':
                    logger.info(f"{log_prefix} Status is PAID - Processing successful payment...")
                    wallet = pending_tx.wallet
                    # This second lock is good for protecting the wallet from other simultaneous operations.
                    wallet_to_update = UserWallet.objects.select_for_update().get(pk=wallet.pk)
                    old_balance = wallet_to_update.balance
                    wallet_to_update.balance += pending_tx.amount
                    wallet_to_update.save(update_fields=['balance', 'updated_at'])

                    pending_tx.status = 'COMPLETED'
                    pending_tx.description = f"Paynow deposit successful. Paynow Ref: {pending_tx.external_reference}"
                    pending_tx.save(update_fields=['status', 'description', 'updated_at'])
                    
                    wallet.refresh_from_db()
                    logger.info(f"{log_prefix} ✓ Payment COMPLETED successfully")
                    logger.info(f"  User: {wallet.user.username}")
                    logger.info(f"  Amount: ${pending_tx.amount}")
                    logger.info(f"  Old Balance: ${old_balance:.2f}")
                    logger.info(f"  New Balance: ${wallet.balance:.2f}")
                    logger.info(f"{log_prefix} Scheduling deposit confirmation notification...")
                    
                    send_deposit_confirmation_whatsapp.delay(
                        whatsapp_id=wallet.user.customer_profile.contact.whatsapp_id,
                        amount=str(pending_tx.amount),
                        new_balance=f"{wallet.balance:.2f}",
                        transaction_reference=transaction_reference,
                        currency_symbol="$"
                    )
                    logger.info("="*80)
                    logger.info(f"TASK END: poll_paynow_transaction_status - SUCCESS (Payment COMPLETED)")
                    logger.info("="*80)
                    return # Task is complete

                elif status.lower() in ['cancelled', 'failed', 'disputed']:
                    reason = f"Paynow transaction status was '{status}'."
                    logger.warning(f"{log_prefix} Payment FAILED - Status: '{status}'")
                    _fail_transaction_and_notify_user(pending_tx, reason)
                    logger.info("="*80)
                    logger.info(f"TASK END: poll_paynow_transaction_status - COMPLETE (Payment FAILED)")
                    logger.info("="*80)
                    return # Task is complete

                else: # 'pending', 'created', 'sent', etc.
                    # Implement exponential backoff with jitter to reduce load on Paynow's servers.
                    # Retries will happen at approx. 60s, 120s, 240s, etc.
                    retry_delay = 60 * (2 ** self.request.retries)
                    retry_delay_with_jitter = retry_delay + random.randint(0, 15) # Add some randomness
                    logger.info(f"{log_prefix} Payment still PENDING - Status: '{status}'")
                    logger.info(f"{log_prefix} Scheduling retry {self.request.retries + 2}/{self.max_retries + 1} in {retry_delay_with_jitter}s...")
                    self.retry(exc=Exception(f"Transaction is still pending. Current status: {status}"), countdown=retry_delay_with_jitter)
            else:
                error_msg = status_response.get('message', 'Unknown API error')
                logger.error(f"{log_prefix} Paynow API error: {error_msg}")
                logger.info(f"{log_prefix} Scheduling retry with default delay...")
                # For API errors, we can use the default retry delay.
                self.retry(exc=Exception(f"Failed to get Paynow status: {error_msg}"))

    except WalletTransaction.DoesNotExist:
        # This is now an expected, non-error outcome for a concurrent task.
        logger.info(f"{log_prefix} Transaction not found or not PENDING. Likely processed by another task.")
        logger.info("="*80)
        logger.info(f"TASK END: poll_paynow_transaction_status - SKIPPED (Already processed)")
        logger.info("="*80)
    except Exception as e:
        logger.error(f"{log_prefix} UNHANDLED ERROR during polling: {e}", exc_info=True)
        try:
            logger.info(f"{log_prefix} Attempting retry...")
            self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error(f"{log_prefix} Max retries exceeded. Attempting to fail transaction.")
            try:
                tx_to_fail = WalletTransaction.objects.get(reference=transaction_reference, status='PENDING')
                _fail_transaction_and_notify_user(tx_to_fail, f"Polling failed after max retries: {str(e)[:100]}")
                logger.info("="*80)
                logger.info(f"TASK END: poll_paynow_transaction_status - FAILED (Max retries exceeded)")
                logger.info("="*80)
            except WalletTransaction.DoesNotExist:
                logger.warning(f"{log_prefix} Could not find transaction to fail after max retries (may have been processed)")
                logger.info("="*80)
                logger.info(f"TASK END: poll_paynow_transaction_status - FAILED (Transaction not found)")
                logger.info("="*80)
            except Exception as final_fail_exc:
                logger.critical(f"{log_prefix} CRITICAL: Could not fail transaction after max retries: {final_fail_exc}")
                logger.info("="*80)
                logger.info(f"TASK END: poll_paynow_transaction_status - CRITICAL ERROR")
                logger.info("="*80)

@shared_task(name="paynow_integration.send_innbucks_authorization_message")
def send_innbucks_authorization_message(transaction_reference: str):
    """
    Sends a WhatsApp message to the user with InnBucks authorization details.
    """
    log_prefix = f"[InnBucks Msg - Ref: {transaction_reference}]"
    logger.info(f"{log_prefix} Preparing to send authorization message.")
    try:
        transaction_obj = WalletTransaction.objects.get(reference=transaction_reference)
        
        authorization_code = transaction_obj.payment_details.get('authorizationcode')
        authorization_expires = transaction_obj.payment_details.get('authorizationexpires')
        whatsapp_id = transaction_obj.wallet.user.customer_profile.contact.whatsapp_id

        if not authorization_code:
            logger.error(f"{log_prefix} Authorization code not found. Cannot send message.")
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


@shared_task(name="paynow_integration.process_paynow_ipn_task")
def process_paynow_ipn_task(ipn_data: dict):
    """
    Processes a Paynow IPN message. It verifies the IPN hash, then triggers
    the polling task to confirm the transaction status before updating the database.
    """
    reference = ipn_data.get('reference')
    if not reference:
        logger.error("[IPN Task] Received IPN data without a reference. Cannot process.")
        return

    log_prefix = f"[IPN Task - Ref: {reference}]"
    logger.info(f"{log_prefix} Starting to process IPN data: {ipn_data}")

    paynow_service = PaynowService()
    if not paynow_service.verify_ipn_hash(ipn_data):
        logger.error(f"{log_prefix} IPN hash verification failed. Discarding message.")
        return

    logger.info(f"{log_prefix} IPN hash verified successfully. Triggering status poll.")

    try:
        # Check if the transaction is still in a state that needs processing.
        if WalletTransaction.objects.filter(reference=reference, status='PENDING').exists():
            poll_paynow_transaction_status.delay(transaction_reference=reference)
            logger.info(f"{log_prefix} Polling task has been scheduled to finalize the transaction.")
        else:
            logger.info(f"{log_prefix} Transaction is not in PENDING state. It was likely already processed. No action taken.")

    except Exception as e:
        logger.error(f"{log_prefix} An unexpected error occurred while triggering the poll task: {e}", exc_info=True)