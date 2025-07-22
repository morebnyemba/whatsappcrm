# whatsappcrm_backend/referrals/models.py

from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
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

class ReferralSettings(models.Model):
    """
    A singleton model to store global settings for the referral program.
    """
    bonus_percentage_each = models.DecimalField(
        max_digits=5,
        decimal_places=4, # Allow for percentages like 2.5% (0.0250)
        default=Decimal('0.2500'),
        help_text="The bonus percentage (e.g., 0.25 for 25%) given to both the referrer and the referred user.",
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))]
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Referral Program Settings"

    def save(self, *args, **kwargs):
        """
        Ensure that only one instance of ReferralSettings can be created.
        """
        self.pk = 1
        super(ReferralSettings, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
