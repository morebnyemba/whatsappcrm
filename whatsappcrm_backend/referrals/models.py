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
    A user must be explicitly designated as an agent by an administrator
    (is_agent=True) before they can share their code or earn commission.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_profile'
    )
    # Whether this user is an active, admin-designated agent.
    is_agent = models.BooleanField(
        default=False,
        help_text="Designate this user as an active agent. Only admin can set this."
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
        """Returns total agent commission earnings (lost-bet commission +
        deposit-referral bonus). Does not net off deductions — see
        total_deductions / net_earnings for the full picture."""
        commission = self.agent_earnings.aggregate(total=models.Sum('commission_amount'))['total'] or Decimal('0.00')
        deposit_bonus = self.deposit_bonuses.aggregate(total=models.Sum('bonus_amount'))['total'] or Decimal('0.00')
        return commission + deposit_bonus

    @property
    def total_deductions(self):
        """Returns total deducted from the agent when referred users win."""
        result = self.agent_deductions.aggregate(total=models.Sum('deduction_amount'))
        return result['total'] or Decimal('0.00')

    @property
    def net_earnings(self):
        """Total earnings minus total win-deductions."""
        return self.total_earnings - self.total_deductions

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

class AgentDeduction(models.Model):
    """
    Tracks amounts deducted from an agent's wallet when a user they referred
    wins a bet — the mirror image of AgentEarning (which credits the agent on
    a referred user's loss).
    """
    agent_profile = models.ForeignKey(
        ReferralProfile,
        on_delete=models.CASCADE,
        related_name='agent_deductions'
    )
    bet_ticket = models.ForeignKey(
        'customer_data.BetTicket',
        on_delete=models.CASCADE,
        related_name='agent_deductions'
    )
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_wins'
    )
    win_amount = models.DecimalField(max_digits=10, decimal_places=2)
    deduction_percentage = models.DecimalField(max_digits=5, decimal_places=4)
    deduction_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f"Agent {self.agent_profile.user.username} was deducted "
            f"${self.deduction_amount} for {self.referred_user.username}'s "
            f"won ticket #{self.bet_ticket_id}"
        )

    class Meta:
        ordering = ['-created_at']

class AgentDepositBonus(models.Model):
    """
    Tracks the agent's own bonus, earned when a user they referred makes
    their qualifying first deposit — paid alongside (not instead of) the
    referred user's own first-deposit bonus.
    """
    agent_profile = models.ForeignKey(
        ReferralProfile,
        on_delete=models.CASCADE,
        related_name='deposit_bonuses'
    )
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_signup_bonuses'
    )
    deposit_transaction = models.ForeignKey(
        'customer_data.WalletTransaction',
        on_delete=models.CASCADE,
        related_name='agent_deposit_bonuses'
    )
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2)
    bonus_percentage = models.DecimalField(max_digits=5, decimal_places=4)
    bonus_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return (
            f"Agent {self.agent_profile.user.username} earned "
            f"${self.bonus_amount} from {self.referred_user.username}'s first deposit"
        )

    class Meta:
        ordering = ['-created_at']
        # Django's default pluralisation would render this "Agent deposit
        # bonuss" in the admin sidebar.
        verbose_name = "Agent Deposit Bonus"
        verbose_name_plural = "Agent Deposit Bonuses"

class ReferralSettings(models.Model):
    """
    A singleton model to store global settings for the agent/referral program.
    """
    bonus_percentage_each = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.2500'),
        help_text="The bonus percentage (e.g., 0.25 for 25%) given to both the referrer (if a "
                   "designated agent) and the referred user on the referred user's qualifying "
                   "first deposit.",
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))]
    )
    agent_commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.2500'),
        help_text="The percentage of a lost bet's stake (e.g., 0.25 for 25%) awarded to the agent who referred the losing bettor.",
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))]
    )
    agent_win_deduction_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.2500'),
        help_text="The percentage of a won bet's winnings (e.g., 0.25 for 25%) deducted from the "
                   "agent's wallet when a user they referred wins.",
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('1.00'))]
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Singleton: Django would otherwise render this "Referral settingss"
        # in the admin sidebar.
        verbose_name = "Agent Program Settings"
        verbose_name_plural = "Agent Program Settings"

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

class AgentApplication(models.Model):
    """
    A user's self-service request to become an agent, submitted from the
    WhatsApp agent-program flow. is_agent itself is still admin-only to
    flip (see ReferralProfile) -- this just gives a user a way to ask,
    and gives an admin a queue to review, instead of the previous dead-end
    "contact support" message with no actual path forward.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='agent_applications'
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+'
    )

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f"Agent application for {self.user.username} ({self.get_status_display()})"
