# whatsappcrm_backend/referrals/models.py

from django.db import models
from django.conf import settings
import string
import random

def _generate_code():
    """Generates a unique 6-character alphanumeric code."""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not ReferralProfile.objects.filter(referral_code=code).exists():
            return code

class ReferralProfile(models.Model):
    """
    Stores referral information for a user, linked to the main User model.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_profile'
    )
    # The user's unique code to share with others.
    referral_code = models.CharField(
        max_length=10, unique=True, default=_generate_code, db_index=True
    )
    # The user who referred this user. Can be null.
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='referrals'
    )
    referral_bonus_applied = models.BooleanField(default=False)

    def __str__(self):
        return f"Referral Profile for {self.user.username}"
