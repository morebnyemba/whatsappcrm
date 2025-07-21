# whatsappcrm_backend/referrals/utils.py

import logging
from django.db import transaction
from decimal import Decimal
from django.contrib.auth import get_user_model

from .models import ReferralProfile
from customer_data.models import UserWallet # We need the wallet to apply the bonus

logger = logging.getLogger(__name__)
User = get_user_model()

REFERRAL_BONUS_AMOUNT = Decimal('5.00') # Example bonus amount

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

def apply_referral_bonus(new_user: User):
    """
    Applies a referral bonus to the new user and the referrer.
    This can be called after a specific action, e.g., first deposit.
    """
    profile = get_or_create_referral_profile(new_user)
    if not profile.referred_by or profile.referral_bonus_applied:
        return {"success": False, "message": "No referrer or bonus already applied."}

    with transaction.atomic():
        # Use the add_funds method from UserWallet for proper transaction logging
        new_user.wallet.add_funds(REFERRAL_BONUS_AMOUNT, description=f"Referral bonus from {profile.referred_by.username}", transaction_type='BONUS')
        profile.referred_by.wallet.add_funds(REFERRAL_BONUS_AMOUNT, description=f"Referral bonus for referring {new_user.username}", transaction_type='BONUS')
        profile.referral_bonus_applied = True
        profile.save(update_fields=['referral_bonus_applied'])

    logger.info(f"Applied referral bonus of {REFERRAL_BONUS_AMOUNT} to {new_user.username} and referrer {profile.referred_by.username}")
    return {"success": True, "message": f"Successfully applied a ${REFERRAL_BONUS_AMOUNT} bonus to you and your friend!"}