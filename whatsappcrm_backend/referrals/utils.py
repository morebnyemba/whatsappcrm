# whatsappcrm_backend/referrals/utils.py

import logging
from django.db import transaction
from decimal import Decimal
from django.contrib.auth import get_user_model
from .models import ReferralProfile, ReferralSettings
from customer_data.models import UserWallet, WalletTransaction, CustomerProfile
from .tasks import send_bonus_notification_task

logger = logging.getLogger(__name__)
User = get_user_model()

def get_or_create_referral_profile(user: User) -> ReferralProfile:
    """
    Retrieves or creates a ReferralProfile for a given user.
    The referral code is generated automatically on creation by the model's default.
    """
    profile, created = ReferralProfile.objects.get_or_create(user=user)
    if created:
        logger.info(f"Created ReferralProfile for user {user.username} with code {profile.referral_code}")
    return profile

def link_referral(new_user: User, referral_code: str):
    """
    Links a new user to a referrer if the code is valid.
    This should be called during account creation.
    """
    if not referral_code:
        return

    try:
        referrer_profile = ReferralProfile.objects.select_related('user').get(referral_code__iexact=referral_code)
        new_user_profile = get_or_create_referral_profile(new_user)
        
        # Prevent self-referral
        if new_user_profile.user == referrer_profile.user:
            logger.warning(f"User {new_user.username} attempted self-referral with code {referral_code}.")
            return

        new_user_profile.referred_by = referrer_profile.user
        new_user_profile.save(update_fields=['referred_by'])
        logger.info(f"User {new_user.username} was successfully referred by {referrer_profile.user.username}")
    except ReferralProfile.DoesNotExist:
        logger.warning(f"Invalid referral code '{referral_code}' used by user {new_user.username}.")

def get_referrer_details_from_code(referral_code: str) -> dict:
    """
    Finds a referrer by their code and returns their details for confirmation.
    """
    if not referral_code:
        return {"success": False, "message": "No code provided."}

    try:
        # Find the profile with the given code
        referrer_profile = ReferralProfile.objects.select_related('user__customer_profile').get(referral_code__iexact=referral_code)
        
        # Get the referrer's user and customer profile
        referrer_user = referrer_profile.user
        referrer_customer_profile = referrer_user.customer_profile
        
        # Construct the name to display, preferring first_name
        referrer_name = referrer_customer_profile.first_name or referrer_user.username
        
        return {
            "success": True,
            "referrer_name": referrer_name,
            "referral_code": referrer_profile.referral_code, # Also return the code itself
            "message": f"Referrer found: {referrer_name}"
        }
    except (ReferralProfile.DoesNotExist, CustomerProfile.DoesNotExist):
        return {"success": False, "message": "Invalid referral code."}
    except Exception as e:
        logger.error(f"Error getting referrer details for code {referral_code}: {e}", exc_info=True)
        return {"success": False, "message": "An unexpected error occurred."}

def apply_referral_bonus(new_user: User, deposit_transaction: WalletTransaction):
    """
    Applies a percentage-based referral bonus to the new user and the referrer
    based on the amount of the first deposit.
    This is an internal function called by check_and_apply_first_deposit_bonus.
    """
    profile = get_or_create_referral_profile(new_user)
    if not profile.referred_by or profile.referral_bonus_applied:
        return {"success": False, "message": "No referrer or bonus already applied."}

    first_deposit_amount = deposit_transaction.amount
    if first_deposit_amount <= 0:
        return {"success": False, "message": "First deposit amount is zero or less."}

    # Calculate the bonus amount for each person from the settings
    settings = ReferralSettings.load()
    bonus_amount = first_deposit_amount * settings.bonus_percentage_each

    referrer_user = profile.referred_by

    with transaction.atomic():
        # Use the add_funds method from UserWallet for proper transaction logging
        new_user.wallet.add_funds(bonus_amount, description=f"Referral bonus from {referrer_user.username}", transaction_type='BONUS')
        referrer_user.wallet.add_funds(bonus_amount, description=f"Referral bonus for referring {new_user.username}", transaction_type='BONUS')
        
        profile.referral_bonus_applied = True
        profile.save(update_fields=['referral_bonus_applied'])

    logger.info(f"Applied referral bonus of ${bonus_amount:.2f} to {new_user.username} and referrer {referrer_user.username} based on a deposit of ${first_deposit_amount:.2f}")

    bonus_percentage_display = f"{settings.bonus_percentage_each:.2%}"
    # Send notifications via Celery tasks
    new_user_message = f"🎉 Congratulations! You've received a ${bonus_amount:.2f} ({bonus_percentage_display}) referral bonus from your friend {referrer_user.username}! As a thank you, they've received a bonus too."
    send_bonus_notification_task.delay(user_id=new_user.id, message=new_user_message)

    referrer_message = f"🎉 Great news! Your friend {new_user.username} made their first deposit of ${first_deposit_amount:.2f}. As a thank you, you've both received a ${bonus_amount:.2f} ({bonus_percentage_display}) bonus!"
    send_bonus_notification_task.delay(user_id=referrer_user.id, message=referrer_message)

    return {"success": True, "message": f"Successfully applied a ${bonus_amount:.2f} bonus to you and your friend!"}

def check_and_apply_first_deposit_bonus(user: User):
    """
    Checks if a user is eligible for a first-deposit referral bonus and applies it.
    This should be called after any successful deposit transaction is completed.
    """
    try:
        profile = get_or_create_referral_profile(user)

        # Condition 1: User must have been referred by someone.
        if not profile.referred_by:
            return

        # Condition 2: The bonus must not have been applied already.
        if profile.referral_bonus_applied:
            return

        # Condition 3: This must be the user's *first* completed deposit.
        # We check if there is exactly one completed deposit transaction for this user's wallet.
        completed_deposits_count = WalletTransaction.objects.filter(
            wallet__user=user,
            transaction_type='DEPOSIT',
            status='COMPLETED'
        ).count()

        if completed_deposits_count == 1:
            # Fetch the actual deposit transaction to get its amount
            first_deposit_transaction = WalletTransaction.objects.get(
                wallet__user=user,
                transaction_type='DEPOSIT',
                status='COMPLETED'
            )
            logger.info(f"User {user.username} has made their first deposit. Applying referral bonus.")
            apply_referral_bonus(user, first_deposit_transaction)

    except Exception as e:
        logger.error(f"Error in check_and_apply_first_deposit_bonus for user {user.username}: {e}", exc_info=True)