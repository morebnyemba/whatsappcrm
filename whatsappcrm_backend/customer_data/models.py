# models.py
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal

class CustomerProfile(models.Model):
    """
    Extended user profile for betting customers
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile',null=True,blank=True)
    contact = models.OneToOneField('conversations.Contact', on_delete=models.SET_NULL, null=True, blank=True, related_name='customerprofile')
    
    # New fields for registration flow
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(max_length=255, unique=True, blank=True, null=True)
    gender = models.CharField(max_length=1, choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')], blank=True, null=True)
    date_of_birth = models.DateField(null=True, blank=True)
    acquisition_source = models.CharField(max_length=100, blank=True, null=True, default='whatsapp_flow')

    # Existing fields (ensure they are still relevant or adjust as needed)
    phone_number = models.CharField(max_length=20, unique=True, blank=True, null=True) # Made nullable as contact has it
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_updated_from_conversation = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last update from a conversation flow.")

    def __str__(self):
        if self.user and self.user.username:
            return f"{self.user.username}'s Profile"
        if self.contact and self.contact.name:
            return f"Profile for {self.contact.name}"
        return f"Profile {self.pk}"

    class Meta:
        verbose_name = "Customer Profile"
        verbose_name_plural = "Customer Profiles"
        ordering = ['-updated_at']

class UserWallet(models.Model):
    """
    UserWallet model to track user's betting balance and transactions.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet - ${self.balance}"

    def add_funds(self, amount: Decimal, description: str, transaction_type: str = 'DEPOSIT', payment_method: str = 'manual', reference: str = None, external_reference: str = None):
        """Add funds to wallet"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.balance += Decimal(str(amount))
        WalletTransaction.objects.create(
            wallet=self,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            status='COMPLETED',
            payment_method=payment_method,
            reference=reference,
            external_reference=external_reference
        )
        self.save()
        return self.balance

    def deduct_funds(self, amount: Decimal, description: str, transaction_type: str = 'WITHDRAWAL', payment_method: str = 'manual'):
        """Deduct funds from wallet"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if self.balance < amount:
            raise ValueError("Insufficient funds")
        self.balance -= Decimal(str(amount))
        WalletTransaction.objects.create(
            wallet=self,
            amount=-amount, # Store deductions as negative amounts for easier accounting
            transaction_type=transaction_type,
            description=description, # Corrected: This was missing in the original diff, but should be there.
            status='COMPLETED',
            payment_method=payment_method
        )
        self.save()
        return self.balance

    class Meta:
        ordering = ['-updated_at']

class WalletTransaction(models.Model):
    """
    WalletTransaction model to track all wallet transactions.
    """
    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAWAL', 'Withdrawal'),
        ('BET_PLACED', 'Bet Placed'),
        ('BET_WON', 'Bet Won'),
        ('BET_LOST', 'Bet Lost'),
        ('BET_REFUNDED', 'Bet Refunded'),
    ]

    TRANSACTION_STATUS = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    wallet = models.ForeignKey(UserWallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS, default='COMPLETED', db_index=True)
    payment_method = models.CharField(max_length=50, null=True, blank=True)
    reference = models.CharField(max_length=255, unique=True, null=True, blank=True, db_index=True, help_text="Our internal unique reference for the transaction.")
    external_reference = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Reference from the external payment gateway (e.g., Paynow).")
    payment_details = models.JSONField(default=dict, blank=True, help_text="Stores details for the payment method, e.g., phone number for mobile money.")

    def __str__(self):
        return f"{self.transaction_type} - ${self.amount} - {self.created_at}"

    class Meta:
        ordering = ['-created_at']


class PendingWithdrawalManager(models.Manager):
    """
    Custom manager for WalletTransaction to filter for pending withdrawal requests.
    """
    def get_queryset(self):
        return super().get_queryset().filter(
            transaction_type='WITHDRAWAL',
            status='PENDING'
        )

class PendingWithdrawal(WalletTransaction):
    objects = PendingWithdrawalManager()
    class Meta:
        proxy = True
        verbose_name = "Pending Withdrawal"
        verbose_name_plural = "Pending Withdrawals"
        ordering = ['-created_at'] # Order by newest first

class BetTicket(models.Model):
    """
    BetTicket model to group multiple bets together.
    """
    class TicketStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PLACED = 'PLACED', 'Placed'
        WON = 'WON', 'Won'
        LOST = 'LOST', 'Lost'
        PARTIAL_WIN = 'PARTIAL_WIN', 'Partial Win' # For system bets, not used in current logic
        REFUNDED = 'REFUNDED', 'Refunded'

    BET_TYPES = [
        ('SINGLE', 'Single Bet'),
        ('MULTIPLE', 'Multiple Bet'),
        ('SYSTEM', 'System Bet'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bet_tickets',null=True,blank=True	)
    total_stake = models.DecimalField(max_digits=10, decimal_places=2)
    potential_winnings = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=TicketStatus.choices, default=TicketStatus.PENDING)
    bet_type = models.CharField(max_length=20, choices=BET_TYPES, default='SINGLE')
    total_odds = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('1.000'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        user_display = self.user.username if self.user else "Anonymous"
        return f"Ticket #{self.id} - {user_display} - ${self.total_stake}"

    def calculate_total_odds(self):
        """Calculate total odds for the ticket based on bet type"""
        bets = self.bets.all()
        if not bets:
            return Decimal('1.000')

        if self.bet_type == 'SINGLE':
            return bets[0].market_outcome.odds
        elif self.bet_type == 'MULTIPLE':
            total_odds = Decimal('1.000')
            for bet in bets:
                total_odds *= bet.market_outcome.odds
            return total_odds
        # System bet logic would be more complex and is omitted for now.

    def calculate_potential_winnings(self):
        """Calculate total potential winnings for all bets in the ticket"""
        self.total_odds = self.calculate_total_odds()
        self.potential_winnings = self.total_stake * self.total_odds
        self.save()
        return self.potential_winnings

    def place_ticket(self):
        """Place all bets in the ticket"""
        if self.status != 'PENDING': # Can only place a pending ticket
            raise ValueError("Ticket has already been placed")
        
        if not self.user:
            raise ValueError("A ticket must have a user to be placed.")

        self.user.wallet.deduct_funds(self.total_stake, f"Bet ticket #{self.id} placed", 'BET_PLACED')
        
        for bet in self.bets.all():
            bet.place_bet()
        self.status = self.TicketStatus.PLACED # Update status after placing
        self.save()
        return self

    def settle_ticket(self):
        """Settle the ticket based on the outcomes of its bets."""
        if self.status not in [self.TicketStatus.PLACED, self.TicketStatus.PENDING]:
            raise ValueError(f"Ticket is not in a settlable state (current: {self.status}).")

        if not self.user:
            raise ValueError("A ticket must have a user to be settled.")

        bets = self.bets.select_related('market_outcome').all()
        if not bets:
            raise ValueError("Cannot settle a ticket with no bets.")
        
        if any(bet.status == Bet.BetStatus.PENDING for bet in bets):
            raise ValueError("Not all bets in the ticket are settled yet.")

        # For MULTIPLE or SINGLE bets, one loss means the whole ticket is lost.
        if any(b.status == Bet.BetStatus.LOST for b in bets):
            self.status = self.TicketStatus.LOST
            self.save()
            return self

        # If we reach here, no bets are LOST. They are either WON or PUSH.
        final_odds = Decimal('1.0')
        for bet in bets:
            if bet.status == Bet.BetStatus.WON:
                final_odds *= bet.market_outcome.odds
            # For PUSH, we do nothing, as multiplying by 1.0 is the default.

        if final_odds > Decimal('1.0'):
            self.status = self.TicketStatus.WON
            winnings = self.total_stake * final_odds
            self.user.wallet.add_funds(winnings, f"Won bet ticket #{self.id}", 'BET_WON')
        else: # This happens if all bets were PUSH, resulting in odds of 1.0
            self.status = self.TicketStatus.REFUNDED
            self.user.wallet.add_funds(self.total_stake, f"Refunded bet ticket #{self.id}", 'BET_REFUNDED')

        self.save()
        return self

    class Meta:
        ordering = ['-created_at']

class Bet(models.Model):
    """
    Bet model to track individual bets on market outcomes.
    """
    class BetStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        WON = 'WON', 'Won'
        LOST = 'LOST', 'Lost'
        PUSH = 'REFUNDED', 'Refunded' # Renamed from REFUNDED to PUSH for clarity


    ticket = models.ForeignKey(BetTicket, on_delete=models.CASCADE, related_name='bets')
    market_outcome = models.ForeignKey('football_data_app.MarketOutcome', on_delete=models.CASCADE, related_name='bets')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    potential_winnings = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=BetStatus.choices, default=BetStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        user_display = self.ticket.user.username if self.ticket and self.ticket.user else "Anonymous"
        return f"{user_display}'s bet on {self.market_outcome} - ${self.amount}"

    def place_bet(self):
        """Place a bet"""
        if self.status != 'PENDING':
            raise ValueError("Bet has already been placed")
        
        self.potential_winnings = self.amount * self.market_outcome.odds
        self.save()
        return self

    def settle_bet(self, result):
        """Settle a bet based on the outcome"""
        if self.status != 'PENDING':
            raise ValueError("Bet has already been settled")
        
        self.status = result
        self.save()
        return self

    class Meta:
        ordering = ['-created_at']

# Signal to create wallet when user is created
@receiver(post_save, sender=User)
def create_user_wallet(sender, instance, created, **kwargs):
    if created:
        UserWallet.objects.create(user=instance)
