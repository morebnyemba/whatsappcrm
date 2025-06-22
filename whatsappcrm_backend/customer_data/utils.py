# utils.py

from decimal import Decimal
import secrets
import string
from django.db import transaction
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
    # This reference should be stored and used to match the IPN callback.
    # For simplicity, we'll use a timestamp + whatsapp_id snippet.
    # In a real system, use a UUID or a dedicated transaction ID from your DB.
    transaction_reference = f"DEP-{profile.id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"

    logger.info(f"Initiating deposit process for {whatsapp_id} via {payment_method}. Ref: {transaction_reference}")

    if payment_method == 'paynow_mobile':
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
            # Store the transaction reference and Paynow reference temporarily if needed
            # (e.g., in a pending_transactions table) to link the IPN callback.
            # For now, we just return the redirect URL.
            return {
                "success": True,
                "message": "Paynow mobile payment initiated.",
                "paynow_reference": paynow_response.get('paynow_reference'),
                "poll_url": paynow_response.get('poll_url'), # New: Store this for status checks
                "instructions": paynow_response.get('instructions'), # New: Display to user
                "transaction_reference": transaction_reference # Our internal reference
            }
        else:
            return paynow_response
    else:
        return {"success": False, "message": f"Unsupported payment method: {payment_method}"}

def record_deposit_transaction(whatsapp_id: str, amount: float, description: str, transaction_id: str = None, payment_method: str = None) -> dict:
    """
    Records a confirmed deposit into the customer's wallet.
    """
    try:
        with transaction.atomic():
            contact = Contact.objects.get(whatsapp_id=whatsapp_id)
            profile = CustomerProfile.objects.get(contact=contact)
            if not profile:
                return {"success": False, "message": f"CustomerProfile not found for WhatsApp ID {whatsapp_id}."}

            # Ensure amount is positive and convert to Decimal
            deposit_amount = Decimal(str(amount))
            if deposit_amount <= 0:
                return {"success": False, "message": "Deposit amount must be positive."}
            
            # Update wallet balance
            profile.wallet_balance = F('wallet_balance') + deposit_amount
            profile.save(update_fields=['wallet_balance'])
            profile.refresh_from_db() # Get updated balance

            WalletTransaction.objects.create(
                customer_profile=profile,
                transaction_type='deposit',
                amount=deposit_amount,
                description=description,
                transaction_id=transaction_id, # Store external transaction ID
                payment_method=payment_method
            )
            logger.info(f"Deposit of {deposit_amount} recorded for {whatsapp_id}. New balance: {profile.wallet_balance}")
            return {
                "success": True,
                "message": f"Deposit of {deposit_amount} successful.",
                "new_balance": float(profile.wallet_balance)
            }
    except Contact.DoesNotExist:
        logger.error(f"Contact not found for WhatsApp ID {whatsapp_id}.")
        return {
            "success": False,
            "message": f"Contact not found for WhatsApp ID {whatsapp_id}."
        }
    except CustomerProfile.DoesNotExist:
        logger.error(f"CustomerProfile not found for WhatsApp ID {whatsapp_id}.")
        return {
            "success": False,
            "message": f"CustomerProfile not found for WhatsApp ID {whatsapp_id}."
        }
    except Exception as e:
        logger.error(f"Error performing deposit for {whatsapp_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during deposit: {str(e)}"}

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
            if not customer_profile:
                return {"success": False, "message": f"CustomerProfile not found for WhatsApp ID {whatsapp_id}."}

            if customer_profile.wallet_balance < Decimal(str(amount)):
                return {"success": False, "message": "Insufficient funds for withdrawal.", "new_balance": float(customer_profile.wallet_balance)}

            customer_profile.wallet_balance = F('wallet_balance') - Decimal(str(amount))
            customer_profile.save(update_fields=['wallet_balance'])
            customer_profile.refresh_from_db()

            WalletTransaction.objects.create(
                customer_profile=customer_profile,
                transaction_type='withdrawal',
                amount=Decimal(str(amount)),
                description=description
            )
            logger.info(f"Withdrawal of {amount} recorded for {whatsapp_id}. New balance: {customer_profile.wallet_balance}")
            return {"success": True, "message": f"Successfully withdrew {amount:.2f}.", "new_balance": float(customer_profile.wallet_balance)}
    except Contact.DoesNotExist:
        logger.error(f"Contact not found for WhatsApp ID {whatsapp_id}.")
        return {"success": False, "message": "Contact not found.", "new_balance": None}
    except CustomerProfile.DoesNotExist:
        logger.error(f"CustomerProfile not found for WhatsApp ID {whatsapp_id}.")
        return {"success": False, "message": "Customer profile not found for this contact.", "new_balance": None}
    except Exception as e:
        logger.error(f"Error during withdrawal for {whatsapp_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during withdrawal: {str(e)}", "new_balance": None}

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
