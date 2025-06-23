# utils.py

from .tasks import send_deposit_confirmation_whatsapp # Import the new Celery task
from decimal import Decimal
import secrets
import string
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from conversations.models import Contact
from .models import CustomerProfile, UserWallet, WalletTransaction
import logging
from typing import Optional, Dict, Any

from paynow_integration.services import PaynowService # Import the new service

logger = logging.getLogger(__name__)

User = get_user_model()

def generate_strong_password(length=12):
    """Generate a strong, random password."""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password

def get_customer_profile(whatsapp_id: str) -> dict:
    """
    Retrieves the CustomerProfile for a given WhatsApp ID.
    """
    try:
        contact = Contact.objects.get(whatsapp_id=whatsapp_id)
        profile = CustomerProfile.objects.get(contact=contact)
        return {"success": True, "profile": profile}
    except Contact.DoesNotExist:
        return {"success": False, "message": f"Contact not found for WhatsApp ID {whatsapp_id}."}
    except CustomerProfile.DoesNotExist:
        return {"success": False, "message": f"CustomerProfile not found for WhatsApp ID {whatsapp_id}."}

def create_or_get_customer_account(
    whatsapp_id: str,
    name: str = None,
    email: str = None,
    first_name: str = None,
    last_name: str = None,
    acquisition_source: str = None,
    initial_balance: float = 0.0
) -> dict:
    """
    Creates or retrieves a Contact, CustomerProfile, and UserWallet.
    Automates the creation of a Django User if not already linked.

    Args:
        whatsapp_id (str): The unique WhatsApp ID of the contact.
        name (str, optional): The name of the contact. Defaults to None.
        email (str, optional): Email for potential User account. Defaults to None.
        first_name (str, optional): First name for CustomerProfile. Defaults to None.
        last_name (str, optional): Last name for CustomerProfile. Defaults to None.
        acquisition_source (str, optional): How the customer was acquired. Defaults to None.
        initial_balance (float, optional): Initial wallet balance. Defaults to 0.0.

    Returns:
        dict: A dictionary containing the contact, customer_profile, user,
              wallet, and a status message.
    """
    try:
        with transaction.atomic():
            # 1. Get or Create Contact
            contact, created_contact = Contact.objects.get_or_create(
                whatsapp_id=whatsapp_id,
                defaults={'name': name or whatsapp_id}
            )
            if not created_contact and name and contact.name != name:
                contact.name = name
                contact.save()

            # 2. Get or Create CustomerProfile
            customer_profile, created_profile = CustomerProfile.objects.get_or_create(contact=contact)

            # Update profile fields if provided and different
            profile_updated = False
            if first_name is not None and customer_profile.first_name != first_name:
                customer_profile.first_name = first_name
                profile_updated = True
            if last_name is not None and customer_profile.last_name != last_name:
                customer_profile.last_name = last_name
                profile_updated = True
            if acquisition_source is not None and customer_profile.acquisition_source != acquisition_source:
                customer_profile.acquisition_source = acquisition_source
                profile_updated = True
            if email is not None and customer_profile.email != email:
                customer_profile.email = email
                profile_updated = True
            if profile_updated:
                customer_profile.save()

            # 3. Ensure Django User is linked or created
            user = customer_profile.user
            generated_password = None # Initialize to None
            user_was_created_in_this_call = False
            if not user:
                # Determine username for the new User account
                username = email if email else whatsapp_id # Prefer email, fall back to whatsapp_id
                # Ensure username is unique
                if User.objects.filter(username=username).exists():
                    # If username (email or whatsapp_id) already exists, append a unique suffix
                    suffix = 1
                    original_username = username
                    while User.objects.filter(username=username).exists():
                        username = f"{original_username}_{suffix}"
                        suffix += 1

                generated_password = generate_strong_password() # Store the generated password
                user = User.objects.create_user(username=username, email=email, password=generated_password)
                user_was_created_in_this_call = True
                customer_profile.user = user
                customer_profile.save()
                print(f"Automated User account created for {whatsapp_id} with username: {username}")
                # In a real system, you might securely store this password or email it to the user.
                # For a WhatsApp bot, you might just rely on the linked user for internal operations.

            # 4. Get or Create UserWallet
            wallet, created_wallet = UserWallet.objects.get_or_create(
                user=user,
                defaults={'balance': initial_balance}
            )
            if created_wallet and initial_balance > 0:
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type=WalletTransaction.DEPOSIT,
                    amount=initial_balance,
                    description="Initial account balance on creation"
                )

            return {
                "success": True,
                "message": "Account processed successfully.",
                "contact": contact,
                "customer_profile": customer_profile,
                "user": user,
                "wallet": wallet,
                "created_contact": created_contact,
                "created_profile": created_profile,
                "created_user": user_was_created_in_this_call,
                "generated_password": generated_password # Include the generated password if a new user was created
            }
    except Exception as e:
        import traceback
        traceback.print_exc() # Print full traceback for debugging
        return {
            "success": False,
            "message": f"Error processing account: {str(e)}",
            "contact": None, "customer_profile": None, "user": None, "wallet": None,
            "created_contact": False, "created_profile": False, "created_user": False
        }


def get_customer_wallet_balance(whatsapp_id: str) -> dict:
    """
    Retrieves the wallet balance for a given WhatsApp contact.

    Args:
        whatsapp_id (str): The WhatsApp ID of the contact.

    Returns:
        dict: A dictionary containing success status, message, and balance (if successful).
    """
    try:
        contact = Contact.objects.get(whatsapp_id=whatsapp_id)
        customer_profile = CustomerProfile.objects.get(contact=contact)
        if not customer_profile.user:
            return {"success": False, "message": "No linked user account found for this contact.", "balance": 0.0}

        wallet = UserWallet.objects.get(user=customer_profile.user)
        return {"success": True, "message": "Balance retrieved successfully.", "balance": float(wallet.balance)}
    except Contact.DoesNotExist:
        return {"success": False, "message": "Contact not found.", "balance": 0.0}
    except CustomerProfile.DoesNotExist:
        return {"success": False, "message": "Customer profile not found for this contact.", "balance": 0.0}
    except UserWallet.DoesNotExist:
        return {"success": False, "message": "Wallet not found for the linked user.", "balance": 0.0}
    except Exception as e:
        return {"success": False, "message": f"Error retrieving balance: {str(e)}", "balance": 0.0}

def perform_deposit(
    whatsapp_id: str,
    amount: float,
    payment_method: str,
    description: str = "Deposit via flow",
    phone_number: Optional[str] = None,
    paynow_method_type: Optional[str] = None
) -> dict:
    """
    Handles a deposit request. For 'manual' method, it directly credits the wallet.
    For 'paynow_mobile', it initiates a payment process.
    """
    if amount <= 0:
        return {"success": False, "message": "Deposit amount must be positive."}

    try:
        with transaction.atomic():
            # Get user and wallet, which is common for all methods
            contact = Contact.objects.get(whatsapp_id=whatsapp_id)
            profile = CustomerProfile.objects.get(contact=contact)
            if not profile.user:
                return {"success": False, "message": "No linked user account found for this contact."}
            wallet = UserWallet.objects.get(user=profile.user)

            if payment_method == 'manual':
                # Directly credit the wallet using the model's method
                # Generate a reference for manual deposits
                manual_ref = f"MANUAL-{profile.id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                
                # Create a PENDING transaction. Wallet balance is NOT updated yet.
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=Decimal(str(amount)),
                    transaction_type='DEPOSIT',
                    status='PENDING', # Key change: status is PENDING
                    payment_method='manual',
                    reference=manual_ref,
                    description=f"Manual deposit request for {amount}. Ref: {manual_ref}"
                )
                logger.info(f"Manual deposit request of {amount} recorded as PENDING for {whatsapp_id}. Ref: {manual_ref}")

                # Do NOT trigger WhatsApp confirmation here; it's for COMPLETED transactions.
                # The flow will send a message about pending approval.
                
                return {
                    "success": True,
                    "message": f"Your manual deposit request for {amount:.2f} has been received and is pending approval. You will be notified once it's processed.",
                    "new_balance": float(wallet.balance) # Return current balance, not new balance
                }
            
            elif payment_method == 'paynow_mobile':
                # This is an initiation, not a direct credit. The IPN will handle completion.
                payment_details = {'phone_number': phone_number}
                return initiate_deposit_process(
                    whatsapp_id=whatsapp_id,
                    amount=amount,
                    description=description,
                    payment_method='paynow_mobile',
                    paynow_method_type=paynow_method_type,
                    payment_details=payment_details
                )
            
            else:
                return {"success": False, "message": f"Unsupported payment method: {payment_method}"}

    except (Contact.DoesNotExist, CustomerProfile.DoesNotExist, UserWallet.DoesNotExist):
        return {"success": False, "message": "Could not find a valid, linked customer account and wallet."}
    except Exception as e:
        logger.error(f"Error performing deposit for {whatsapp_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during deposit: {str(e)}"}

def initiate_deposit_process(
    whatsapp_id: str,
    amount: float,
    description: str,
    payment_method: str,
    paynow_method_type: Optional[str] = None, # e.g., 'ecocash', 'onemoney'
    payment_details: dict = None # e.g., {'phone_number': '26377xxxxxxx'} for mobile
) -> dict:
    """
    Initiates a deposit process, potentially involving an external payment gateway.
    This function does NOT directly update the wallet balance.
    It returns instructions for the flow (e.g., a redirect URL).
    """
    if not payment_details:
        payment_details = {}

    profile_result = get_customer_profile(whatsapp_id)
    if not profile_result['success']:
        return profile_result # Return error if profile not found
    
    profile = profile_result['profile']
    
    # Generate a unique reference for this transaction
    transaction_reference = f"DEP-{profile.id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"

    logger.info(f"Initiating deposit process for {whatsapp_id} via {payment_method}. Ref: {transaction_reference}")

    if payment_method == 'paynow_mobile':
        # Create a PENDING transaction record before calling Paynow.
        # The wallet balance is NOT updated yet.
        try:
            wallet = UserWallet.objects.get(user=profile.user)
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=Decimal(str(amount)),
                transaction_type='DEPOSIT',
                status='PENDING',
                reference=transaction_reference,
                payment_method=payment_method,
                description=f"Pending Paynow deposit for {amount}. Ref: {transaction_reference}"
            )
        except UserWallet.DoesNotExist:
            return {"success": False, "message": "User wallet not found."}
        except Exception as e:
            logger.error(f"Failed to create pending transaction record for {whatsapp_id}: {e}", exc_info=True)
            return {"success": False, "message": "Internal error while preparing deposit."}

        paynow_service = PaynowService()
        phone_number = payment_details.get('phone_number')
        email = profile.user.email if profile.user and profile.user.email else f"{whatsapp_id}@example.com" # Fallback email

        if not paynow_method_type:
            logger.error(f"Paynow mobile deposit initiated without a specific Paynow method type (e.g., 'ecocash') for {whatsapp_id}.")
            return {"success": False, "message": "Specific Paynow method type (e.g., EcoCash, OneMoney) is required."}

        if not phone_number:
            logger.error(f"Paynow mobile deposit initiated without phone number for {whatsapp_id}.")
            return {"success": False, "message": "Phone number is required for Paynow mobile deposit."}

        paynow_response = paynow_service.initiate_express_checkout_payment(
            amount=Decimal(str(amount)), # Ensure Decimal type
            reference=transaction_reference,
            phone_number=phone_number,
            email=email,
            paynow_method_type=paynow_method_type,
            description=description
        )
        if paynow_response['success']:
            # Update the pending transaction with the external reference from Paynow
            try:
                pending_tx = WalletTransaction.objects.get(reference=transaction_reference)
                pending_tx.external_reference = paynow_response.get('paynow_reference')
                pending_tx.save(update_fields=['external_reference'])
            except WalletTransaction.DoesNotExist:
                logger.error(f"Could not find pending transaction with ref {transaction_reference} to update external_reference.")
                return {"success": False, "message": "Internal error: could not link payment gateway transaction."}

            return {
                "success": True,
                "message": "Paynow mobile payment initiated.",
                "paynow_reference": paynow_response.get('paynow_reference'),
                "poll_url": paynow_response.get('poll_url'),
                "instructions": paynow_response.get('instructions'),
                "transaction_reference": transaction_reference # Our internal reference
            }
        else:
            # If Paynow initiation fails, mark our pending transaction as FAILED.
            try:
                pending_tx = WalletTransaction.objects.get(reference=transaction_reference)
                pending_tx.status = 'FAILED'
                pending_tx.description = f"Paynow initiation failed: {paynow_response.get('message', 'Unknown error')}"
                pending_tx.save(update_fields=['status', 'description'])
            except WalletTransaction.DoesNotExist:
                logger.error(f"Could not find pending transaction with ref {transaction_reference} to mark as failed.")
            return paynow_response
    else:
        return {"success": False, "message": f"Unsupported payment method: {payment_method}"}

def process_paynow_ipn(ipn_data: Dict[str, Any]) -> dict:
    """
    Processes an IPN from Paynow, validates it, and updates the wallet if successful.
    This function is designed to be idempotent.
    """
    logger.info(f"Processing Paynow IPN: {ipn_data}")
    paynow_service = PaynowService()

    # 1. Validate the hash to ensure the request is from Paynow
    if not paynow_service.is_ipn_authentic(ipn_data):
        logger.error(f"Paynow IPN with invalid hash received. Reference: {ipn_data.get('reference')}")
        return {"success": False, "message": "Invalid IPN hash."}

    # 2. Extract key fields from the IPN
    internal_ref = ipn_data.get('reference')
    paynow_ref = ipn_data.get('paynowreference')
    amount_paid_str = ipn_data.get('amount')
    status = ipn_data.get('status')

    if not all([internal_ref, paynow_ref, amount_paid_str, status]):
        logger.error(f"Paynow IPN is missing one or more required fields. Data: {ipn_data}")
        return {"success": False, "message": "Missing required fields in IPN."}

    try:
        with transaction.atomic():
            # 3. Find the corresponding PENDING transaction in our system
            try:
                pending_tx = WalletTransaction.objects.select_for_update().get(reference=internal_ref, status='PENDING')
            except WalletTransaction.DoesNotExist:
                if WalletTransaction.objects.filter(reference=internal_ref, status='COMPLETED').exists():
                    logger.info(f"Received duplicate IPN for already completed transaction. Ref: {internal_ref}. Ignoring.")
                    return {"success": True, "message": "Duplicate IPN for completed transaction."}
                else:
                    logger.error(f"Received IPN for an unknown or non-pending transaction. Ref: {internal_ref}.")
                    return {"success": False, "message": "Transaction not found or not in a pending state."}

            # 4. Process based on the IPN status
            wallet = pending_tx.wallet
            amount_paid = Decimal(amount_paid_str)

            if amount_paid != pending_tx.amount:
                logger.error(f"Amount mismatch for transaction Ref {internal_ref}. Expected: {pending_tx.amount}, IPN Amount: {amount_paid}. Marking as FAILED.")
                pending_tx.status = 'FAILED'
                pending_tx.description = f"IPN amount mismatch. Expected {pending_tx.amount}, got {amount_paid}."
                pending_tx.save()
                return {"success": False, "message": "Amount mismatch."}

            if status.lower() in ['paid', 'delivered']:
                wallet.balance += amount_paid
                wallet.save(update_fields=['balance'])
                pending_tx.status = 'COMPLETED'
                pending_tx.description = f"Paynow deposit successful. Paynow Ref: {paynow_ref}"
                pending_tx.save()
                logger.info(f"Successfully processed deposit for Ref {internal_ref}. User: {wallet.user.username}, Amount: {amount_paid}. New balance: {wallet.balance}")

                # Trigger WhatsApp notification via Celery task
                # We pass arguments as strings as it's best practice for Celery
                send_deposit_confirmation_whatsapp.delay(
                    whatsapp_id=wallet.user.customer_profile.contact.whatsapp_id,
                    amount=str(amount_paid),
                    new_balance=str(wallet.balance),
                    transaction_reference=internal_ref,
                    currency_symbol="$" # Pass the currency symbol
                )
            elif status.lower() in ['cancelled', 'failed', 'disputed']:
                pending_tx.status = 'CANCELLED' if status.lower() == 'cancelled' else 'FAILED'
                pending_tx.description = f"Paynow transaction status: {status}. Paynow Ref: {paynow_ref}"
                pending_tx.save()
                logger.warning(f"Paynow transaction for Ref {internal_ref} was not successful. Status: {status}.")
            else:
                logger.info(f"Received non-final IPN status '{status}' for Ref {internal_ref}. No action taken.")
            return {"success": True, "message": "IPN processed."}
    except Exception as e:
        logger.error(f"Critical error processing IPN for Ref {internal_ref}: {e}", exc_info=True)
        return {"success": False, "message": f"Internal server error: {e}"}

def process_manual_deposit_approval(transaction_reference: str) -> dict:
    """
    Processes the approval of a PENDING manual deposit transaction.
    Increments the wallet balance and updates the transaction status to COMPLETED.
    """
    logger.info(f"Attempting to approve manual deposit for reference: {transaction_reference}")
    try:
        with transaction.atomic():
            # Find the PENDING manual transaction
            manual_tx = WalletTransaction.objects.select_for_update().get(
                reference=transaction_reference,
                status='PENDING',
                payment_method='manual',
                transaction_type='DEPOSIT'
            )

            wallet = manual_tx.wallet
            amount_to_add = manual_tx.amount

            # Increment wallet balance
            wallet.balance += amount_to_add
            wallet.save(update_fields=['balance'])

            # Update transaction status to COMPLETED
            manual_tx.status = 'COMPLETED'
            manual_tx.description = f"Manual deposit approved. Ref: {transaction_reference}"
            manual_tx.save(update_fields=['status', 'description'])

            logger.info(f"Manual deposit {transaction_reference} approved. Wallet {wallet.user.username} new balance: {wallet.balance}")

            # Trigger WhatsApp confirmation message
            send_deposit_confirmation_whatsapp.delay(
                whatsapp_id=wallet.user.customer_profile.contact.whatsapp_id,
                amount=str(amount_to_add),
                new_balance=str(wallet.balance),
                transaction_reference=transaction_reference,
                currency_symbol="$" # Assuming default currency symbol
            )
            return {"success": True, "message": f"Manual deposit {transaction_reference} approved successfully."}

    except WalletTransaction.DoesNotExist:
        logger.error(f"Manual deposit transaction with reference {transaction_reference} not found, not pending, or not a manual deposit.")
        return {"success": False, "message": "Transaction not found, not pending, or not a manual deposit."}
    except CustomerProfile.DoesNotExist:
        logger.error(f"CustomerProfile not found for wallet linked to transaction {transaction_reference}.")
        return {"success": False, "message": "Customer profile not found for linked user."}
    except Exception as e:
        logger.error(f"Error approving manual deposit {transaction_reference}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during approval: {str(e)}"}

def perform_withdrawal(whatsapp_id: str, amount: float, description: str = "Withdrawal via flow") -> dict:
    """
    Performs a withdrawal from the customer's wallet.

    Args:
        whatsapp_id (str): The WhatsApp ID of the contact.
        amount (float): The amount to withdraw.
        description (str, optional): Description for the transaction. Defaults to "Withdrawal via flow".

    Returns:
        dict: A dictionary containing success status, message, new balance (if successful).
    """
    if amount <= 0:
        return {"success": False, "message": "Withdrawal amount must be positive.", "new_balance": None}

    try:
        with transaction.atomic():
            contact = Contact.objects.get(whatsapp_id=whatsapp_id)
            customer_profile = CustomerProfile.objects.get(contact=contact)
            if not customer_profile.user:
                return {"success": False, "message": "No linked user account found for this contact.", "new_balance": None}

            wallet = UserWallet.objects.get(user=customer_profile.user)

            # The wallet's deduct_funds method will raise ValueError for insufficient funds
            new_balance = wallet.deduct_funds(Decimal(str(amount)), description, 'WITHDRAWAL', payment_method='manual')

            logger.info(f"Withdrawal of {amount} recorded for {whatsapp_id}. New balance: {new_balance}")
            return {"success": True, "message": f"Successfully withdrew {amount:.2f}.", "new_balance": float(new_balance)}
    except (Contact.DoesNotExist, CustomerProfile.DoesNotExist, UserWallet.DoesNotExist):
        return {"success": False, "message": "Could not find a valid, linked customer account and wallet.", "new_balance": None}
    except ValueError as e: # Catches insufficient funds from wallet.deduct_funds
        logger.warning(f"Withdrawal failed for {whatsapp_id}: {e}")
        # To return the current balance, we need to fetch the wallet again if the transaction was rolled back
        try:
            wallet = UserWallet.objects.get(user__customer_profile__contact__whatsapp_id=whatsapp_id)
            current_balance = float(wallet.balance)
        except (UserWallet.DoesNotExist, CustomerProfile.DoesNotExist, Contact.DoesNotExist):
            current_balance = None
        return {"success": False, "message": str(e), "new_balance": current_balance}
    except Exception as e:
        logger.error(f"Error during withdrawal for {whatsapp_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during withdrawal: {str(e)}", "new_balance": None}
                    whatsapp_id=whatsapp_id,
                    amount=str(amount),
                    new_balance=str(new_balance),
                    transaction_reference=manual_ref,
                    currency_symbol="$" # Pass the currency symbol
                )
                return {
                    "success": True,
                    "message": f"Deposit of {amount:.2f} successful.",
                    "new_balance": float(new_balance)
                }
            
            elif payment_method == 'paynow_mobile':
                # This is an initiation, not a direct credit.
                payment_details = {'phone_number': phone_number}
                return initiate_deposit_process(
                    whatsapp_id=whatsapp_id,
                    amount=amount,
                    description=description,
                    payment_method='paynow_mobile',
                    paynow_method_type=paynow_method_type,
                    payment_details=payment_details
                )
            
            else:
                return {"success": False, "message": f"Unsupported payment method: {payment_method}"}

    except (Contact.DoesNotExist, CustomerProfile.DoesNotExist, UserWallet.DoesNotExist):
        return {"success": False, "message": "Could not find a valid, linked customer account and wallet."}
    except Exception as e:
        logger.error(f"Error performing deposit for {whatsapp_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during deposit: {str(e)}"}

def initiate_deposit_process(
    whatsapp_id: str,
    amount: float,
    description: str,
    payment_method: str,
    paynow_method_type: Optional[str] = None, # e.g., 'ecocash', 'onemoney'
    payment_details: dict = None # e.g., {'phone_number': '26377xxxxxxx'} for mobile
) -> dict:
    """
    Initiates a deposit process, potentially involving an external payment gateway.
    This function does NOT directly update the wallet balance.
    It returns instructions for the flow (e.g., a redirect URL).
    """
    if not payment_details:
        payment_details = {}

    profile_result = get_customer_profile(whatsapp_id)
    if not profile_result['success']:
        return profile_result # Return error if profile not found
    
    profile = profile_result['profile']
    
    # Generate a unique reference for this transaction
    transaction_reference = f"DEP-{profile.id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"

    logger.info(f"Initiating deposit process for {whatsapp_id} via {payment_method}. Ref: {transaction_reference}")

    if payment_method == 'paynow_mobile':
        # Create a PENDING transaction record before calling Paynow.
        # The wallet balance is NOT updated yet.
        try:
            wallet = UserWallet.objects.get(user=profile.user)
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=Decimal(str(amount)),
                transaction_type='DEPOSIT',
                status='PENDING',
                reference=transaction_reference,
                payment_method=payment_method,
                description=f"Pending Paynow deposit for {amount}. Ref: {transaction_reference}"
            )
        except UserWallet.DoesNotExist:
            return {"success": False, "message": "User wallet not found."}
        except Exception as e:
            logger.error(f"Failed to create pending transaction record for {whatsapp_id}: {e}", exc_info=True)
            return {"success": False, "message": "Internal error while preparing deposit."}

        paynow_service = PaynowService()
        phone_number = payment_details.get('phone_number')
        email = profile.user.email if profile.user and profile.user.email else f"{whatsapp_id}@example.com" # Fallback email

        if not paynow_method_type:
            logger.error(f"Paynow mobile deposit initiated without a specific Paynow method type (e.g., 'ecocash') for {whatsapp_id}.")
            return {"success": False, "message": "Specific Paynow method type (e.g., EcoCash, OneMoney) is required."}

        if not phone_number:
            logger.error(f"Paynow mobile deposit initiated without phone number for {whatsapp_id}.")
            return {"success": False, "message": "Phone number is required for Paynow mobile deposit."}

        paynow_response = paynow_service.initiate_express_checkout_payment(
            amount=Decimal(str(amount)), # Ensure Decimal type
            reference=transaction_reference,
            phone_number=phone_number,
            email=email,
            paynow_method_type=paynow_method_type,
            description=description
        )
        if paynow_response['success']:
            # Update the pending transaction with the external reference from Paynow
            try:
                pending_tx = WalletTransaction.objects.get(reference=transaction_reference)
                pending_tx.external_reference = paynow_response.get('paynow_reference')
                pending_tx.save(update_fields=['external_reference'])
            except WalletTransaction.DoesNotExist:
                logger.error(f"Could not find pending transaction with ref {transaction_reference} to update external_reference.")
                return {"success": False, "message": "Internal error: could not link payment gateway transaction."}

            return {
                "success": True,
                "message": "Paynow mobile payment initiated.",
                "paynow_reference": paynow_response.get('paynow_reference'),
                "poll_url": paynow_response.get('poll_url'),
                "instructions": paynow_response.get('instructions'),
                "transaction_reference": transaction_reference # Our internal reference
            }
        else:
            # If Paynow initiation fails, mark our pending transaction as FAILED.
            try:
                pending_tx = WalletTransaction.objects.get(reference=transaction_reference)
                pending_tx.status = 'FAILED'
                pending_tx.description = f"Paynow initiation failed: {paynow_response.get('message', 'Unknown error')}"
                pending_tx.save(update_fields=['status', 'description'])
            except WalletTransaction.DoesNotExist:
                logger.error(f"Could not find pending transaction with ref {transaction_reference} to mark as failed.")
            return paynow_response
    else:
        return {"success": False, "message": f"Unsupported payment method: {payment_method}"}

def process_paynow_ipn(ipn_data: Dict[str, Any]) -> dict:
    """
    Processes an IPN from Paynow, validates it, and updates the wallet if successful.
    This function is designed to be idempotent.
    """
    logger.info(f"Processing Paynow IPN: {ipn_data}")
    paynow_service = PaynowService()

    # 1. Validate the hash to ensure the request is from Paynow
    if not paynow_service.is_ipn_authentic(ipn_data):
        logger.error(f"Paynow IPN with invalid hash received. Reference: {ipn_data.get('reference')}")
        return {"success": False, "message": "Invalid IPN hash."}

    # 2. Extract key fields from the IPN
    internal_ref = ipn_data.get('reference')
    paynow_ref = ipn_data.get('paynowreference')
    amount_paid_str = ipn_data.get('amount')
    status = ipn_data.get('status')

    if not all([internal_ref, paynow_ref, amount_paid_str, status]):
        logger.error(f"Paynow IPN is missing one or more required fields. Data: {ipn_data}")
        return {"success": False, "message": "Missing required fields in IPN."}

    try:
        with transaction.atomic():
            # 3. Find the corresponding PENDING transaction in our system
            try:
                pending_tx = WalletTransaction.objects.select_for_update().get(reference=internal_ref, status='PENDING')
            except WalletTransaction.DoesNotExist:
                if WalletTransaction.objects.filter(reference=internal_ref, status='COMPLETED').exists():
                    logger.info(f"Received duplicate IPN for already completed transaction. Ref: {internal_ref}. Ignoring.")
                    return {"success": True, "message": "Duplicate IPN for completed transaction."}
                else:
                    logger.error(f"Received IPN for an unknown or non-pending transaction. Ref: {internal_ref}.")
                    return {"success": False, "message": "Transaction not found or not in a pending state."}

            # 4. Process based on the IPN status
            wallet = pending_tx.wallet
            amount_paid = Decimal(amount_paid_str)

            if amount_paid != pending_tx.amount:
                logger.error(f"Amount mismatch for transaction Ref {internal_ref}. Expected: {pending_tx.amount}, IPN Amount: {amount_paid}. Marking as FAILED.")
                pending_tx.status = 'FAILED'
                pending_tx.description = f"IPN amount mismatch. Expected {pending_tx.amount}, got {amount_paid}."
                pending_tx.save()
                return {"success": False, "message": "Amount mismatch."}

            if status.lower() in ['paid', 'delivered']:
                wallet.balance += amount_paid
                wallet.save(update_fields=['balance'])
                pending_tx.status = 'COMPLETED'
                pending_tx.description = f"Paynow deposit successful. Paynow Ref: {paynow_ref}"
                pending_tx.save()
                logger.info(f"Successfully processed deposit for Ref {internal_ref}. User: {wallet.user.username}, Amount: {amount_paid}. New balance: {wallet.balance}")

                # Trigger WhatsApp notification via Celery task
                # We pass arguments as strings as it's best practice for Celery
                send_deposit_confirmation_whatsapp.delay(
                    whatsapp_id=wallet.user.customer_profile.contact.whatsapp_id,
                    amount=str(amount_paid),
                    new_balance=str(wallet.balance),
                    transaction_reference=internal_ref,
                    currency_symbol="$" # Pass the currency symbol
                )
            elif status.lower() in ['cancelled', 'failed', 'disputed']:
                pending_tx.status = 'CANCELLED' if status.lower() == 'cancelled' else 'FAILED'
                pending_tx.description = f"Paynow transaction status: {status}. Paynow Ref: {paynow_ref}"
                pending_tx.save()
                logger.warning(f"Paynow transaction for Ref {internal_ref} was not successful. Status: {status}.")
            else:
                logger.info(f"Received non-final IPN status '{status}' for Ref {internal_ref}. No action taken.")
            return {"success": True, "message": "IPN processed."}
    except Exception as e:
        logger.error(f"Critical error processing IPN for Ref {internal_ref}: {e}", exc_info=True)
        return {"success": False, "message": f"Internal server error: {e}"}

def perform_withdrawal(whatsapp_id: str, amount: float, description: str = "Withdrawal via flow") -> dict:
    """
    Performs a withdrawal from the customer's wallet.

    Args:
        whatsapp_id (str): The WhatsApp ID of the contact.
        amount (float): The amount to withdraw.
        description (str, optional): Description for the transaction. Defaults to "Withdrawal via flow".

    Returns:
        dict: A dictionary containing success status, message, new balance (if successful).
    """
    if amount <= 0:
        return {"success": False, "message": "Withdrawal amount must be positive.", "new_balance": None}

    try:
        with transaction.atomic():
            contact = Contact.objects.get(whatsapp_id=whatsapp_id)
            customer_profile = CustomerProfile.objects.get(contact=contact)
            if not customer_profile.user:
                return {"success": False, "message": "No linked user account found for this contact.", "new_balance": None}

            wallet = UserWallet.objects.get(user=customer_profile.user)

            # The wallet's deduct_funds method will raise ValueError for insufficient funds
            new_balance = wallet.deduct_funds(Decimal(str(amount)), description, 'WITHDRAWAL', payment_method='manual')

            logger.info(f"Withdrawal of {amount} recorded for {whatsapp_id}. New balance: {new_balance}")
            return {"success": True, "message": f"Successfully withdrew {amount:.2f}.", "new_balance": float(new_balance)}
    except (Contact.DoesNotExist, CustomerProfile.DoesNotExist, UserWallet.DoesNotExist):
        return {"success": False, "message": "Could not find a valid, linked customer account and wallet.", "new_balance": None}
    except ValueError as e: # Catches insufficient funds from wallet.deduct_funds
        logger.warning(f"Withdrawal failed for {whatsapp_id}: {e}")
        # To return the current balance, we need to fetch the wallet again if the transaction was rolled back
        try:
            wallet = UserWallet.objects.get(user__customer_profile__contact__whatsapp_id=whatsapp_id)
            current_balance = float(wallet.balance)
        except (UserWallet.DoesNotExist, CustomerProfile.DoesNotExist, Contact.DoesNotExist):
            current_balance = None
        return {"success": False, "message": str(e), "new_balance": current_balance}
    except Exception as e:
        logger.error(f"Error during withdrawal for {whatsapp_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during withdrawal: {str(e)}", "new_balance": None}
