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
    Stores agent/referral information for a user, linked to the main User model.
    Each user with a referral code acts as an agent who can earn commission
    when users they referred lose bets.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_profile'
    )
    # The user's unique agent code to share with others.
    referral_code = models.CharField(
        max_length=10, unique=True, default=_generate_code, db_index=True
    )
    # The agent (user) who referred this user. Can be null.
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='referrals'
    )
    referral_bonus_applied = models.BooleanField(default=False)

    def __str__(self):
        return f"Agent Profile for {self.user.username}"

    @property
    def total_earnings(self):
        """Returns total agent commission earnings."""
        result = self.agent_earnings.aggregate(total=models.Sum('commission_amount'))
        return result['total'] or Decimal('0.00')

class AgentEarning(models.Model):
    """
    Tracks individual commission earnings for an agent when a referred user loses a bet.
    """
    agent_profile = models.ForeignKey(
        ReferralProfile,
        on_delete=models.CASCADE,
        related_name='agent_earnings'
    )
    bet_ticket = models.ForeignKey(
        'customer_data.BetTicket',
        on_delete=models.CASCADE,
        related_name='agent_earnings'
    )
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_losses'
    )
    bet_stake = models.DecimalField(max_digits=10, decimal_places=2)
    commission_percentage = models.DecimalField(max_digits=5, decimal_places=4)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f"Agent {self.agent_profile.user.username} earned "
            f"${self.commission_amount} from {self.referred_user.username}'s "
            f"lost ticket #{self.bet_ticket_id}"
        )

    class Meta:
        ordering = ['-created_at']

class ReferralSettings(models.Model):
    """
    A singleton model to store global settings for the agent/referral program.
    """
    bonus_percentage_each = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.2500'),
        help_text="The bonus percentage (e.g., 0.25 for 25%) given to both the referrer and the referred user on first deposit.",
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))]
    )
    agent_commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0500'),
        help_text="The percentage of a lost bet's stake (e.g., 0.05 for 5%) awarded to the agent who referred the losing bettor.",
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))]
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Agent Program Settings"

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
