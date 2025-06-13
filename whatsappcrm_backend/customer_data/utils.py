# whatsappcrm_backend/customer_data/utils.py

import secrets
import string
from django.db import transaction
from django.contrib.auth import get_user_model
from conversations.models import Contact
from .models import CustomerProfile, UserWallet, WalletTransaction

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
            customer_profile, created_profile = CustomerProfile.objects.get_or_create(
                contact=contact,
                defaults={
                    'first_name': first_name or '',
                    'last_name': last_name or '',
                    'acquisition_source': acquisition_source or 'whatsapp_flow'
                }
            )
            # Update profile if it exists and fields are provided
            if not created_profile:
                if first_name and customer_profile.first_name != first_name:
                    customer_profile.first_name = first_name
                if last_name and customer_profile.last_name != last_name:
                    customer_profile.last_name = last_name
                if acquisition_source and customer_profile.acquisition_source != acquisition_source:
                    customer_profile.acquisition_source = acquisition_source
                customer_profile.save()

            # 3. Ensure Django User is linked or created
            user = customer_profile.user
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

                password = generate_strong_password()
                user = User.objects.create_user(username=username, email=email, password=password)
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
                "created_user": (user is not None and created_profile) # Indicates if user was newly created in this call
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


def perform_deposit(whatsapp_id: str, amount: float, description: str = "Deposit via flow") -> dict:
    """
    Performs a deposit into the customer's wallet.

    Args:
        whatsapp_id (str): The WhatsApp ID of the contact.
        amount (float): The amount to deposit.
        description (str, optional): Description for the transaction. Defaults to "Deposit via flow".

    Returns:
        dict: A dictionary containing success status, message, new balance (if successful).
    """
    if amount <= 0:
        return {"success": False, "message": "Deposit amount must be positive.", "new_balance": None}

    try:
        with transaction.atomic():
            contact = Contact.objects.get(whatsapp_id=whatsapp_id)
            customer_profile = CustomerProfile.objects.get(contact=contact)
            if not customer_profile.user:
                return {"success": False, "message": "No linked user account found for this contact. Cannot deposit.", "new_balance": None}

            wallet = UserWallet.objects.get(user=customer_profile.user)
            wallet.add_funds(amount, description, WalletTransaction.DEPOSIT)
            return {"success": True, "message": f"Successfully deposited {amount:.2f}.", "new_balance": float(wallet.balance)}
    except Contact.DoesNotExist:
        return {"success": False, "message": "Contact not found.", "new_balance": None}
    except CustomerProfile.DoesNotExist:
        return {"success": False, "message": "Customer profile not found for this contact.", "new_balance": None}
    except UserWallet.DoesNotExist:
        return {"success": False, "message": "Wallet not found for the linked user.", "new_balance": None}
    except Exception as e:
        return {"success": False, "message": f"Error during deposit: {str(e)}", "new_balance": None}


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
                return {"success": False, "message": "No linked user account found for this contact. Cannot withdraw.", "new_balance": None}

            wallet = UserWallet.objects.get(user=customer_profile.user)
            if wallet.balance < amount:
                return {"success": False, "message": "Insufficient funds for withdrawal.", "new_balance": float(wallet.balance)}

            wallet.deduct_funds(amount, description, WalletTransaction.WITHDRAWAL)
            return {"success": True, "message": f"Successfully withdrew {amount:.2f}.", "new_balance": float(wallet.balance)}
    except Contact.DoesNotExist:
        return {"success": False, "message": "Contact not found.", "new_balance": None}
    except CustomerProfile.DoesNotExist:
        return {"success": False, "message": "Customer profile not found for this contact.", "new_balance": None}
    except UserWallet.DoesNotExist:
        return {"success": False, "message": "Wallet not found for the linked user.", "new_balance": None}
    except Exception as e:
        return {"success": False, "message": f"Error during withdrawal: {str(e)}", "new_balance": None}