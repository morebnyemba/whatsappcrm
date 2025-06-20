# whatsappcrm_backend/customer_data/models.py

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
    contact = models.OneToOneField('conversations.Contact', on_delete=models.SET_NULL, null=True, blank=True, related_name='customer_profile')
    phone_number = models.CharField(max_length=20, unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

    def add_funds(self, amount):
        """Add funds to wallet"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.balance += Decimal(str(amount))
        self.save()
        return self.balance

    def deduct_funds(self, amount):
        """Deduct funds from wallet"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if self.balance < amount:
            raise ValueError("Insufficient funds")
        self.balance -= Decimal(str(amount))
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

    wallet = models.ForeignKey(UserWallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction_type} - ${self.amount} - {self.created_at}"

    class Meta:
        ordering = ['-created_at']

class BetTicket(models.Model):
    """
    BetTicket model to group multiple bets together.
    """
    TICKET_STATUS = [
        ('PENDING', 'Pending'),
        ('WON', 'Won'),
        ('LOST', 'Lost'),
        ('PARTIAL_WIN', 'Partial Win'),
        ('REFUNDED', 'Refunded'),
    ]

    BET_TYPES = [
        ('SINGLE', 'Single Bet'),
        ('MULTIPLE', 'Multiple Bet'),
        ('SYSTEM', 'System Bet'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bet_tickets',null=True,blank=True	)
    total_stake = models.DecimalField(max_digits=10, decimal_places=2)
    potential_winnings = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=TICKET_STATUS, default='PENDING')
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
        elif self.bet_type == 'SYSTEM':
            total_odds = Decimal('0.000')
            bet_odds = [bet.market_outcome.odds for bet in bets]
            
            from itertools import combinations
            for r in range(2, len(bet_odds) + 1):
                for combo in combinations(bet_odds, r):
                    combo_odds = Decimal('1.000')
                    for odds in combo:
                        combo_odds *= odds
                    total_odds += combo_odds
            
            return total_odds

    def calculate_potential_winnings(self):
        """Calculate total potential winnings for all bets in the ticket"""
        self.total_odds = self.calculate_total_odds()
        self.potential_winnings = self.total_stake * self.total_odds
        self.save()
        return self.potential_winnings

    def place_ticket(self):
        """Place all bets in the ticket"""
        if self.status != 'PENDING':
            raise ValueError("Ticket has already been placed")
        
        if not self.user:
            raise ValueError("A ticket must have a user to be placed.")

        self.user.wallet.deduct_funds(self.total_stake)
        
        WalletTransaction.objects.create(
            wallet=self.user.wallet,
            amount=self.total_stake,
            transaction_type='BET_PLACED',
            description=f"Bet ticket #{self.id} placed"
        )
        
        for bet in self.bets.all():
            bet.place_bet()
        
        self.save()
        return self

    def settle_ticket(self):
        """Settle all bets in the ticket and update status"""
        if self.status != 'PENDING':
            raise ValueError("Ticket has already been settled")
        
        if not self.user:
            raise ValueError("A ticket must have a user to be settled.")

        bets = self.bets.all()
        if not bets:
            raise ValueError("No bets found in ticket")
        
        if not all(bet.status != 'PENDING' for bet in bets):
            raise ValueError("Not all bets are settled")
        
        if all(bet.status == 'WON' for bet in bets):
            self.status = 'WON'
            self.user.wallet.add_funds(self.potential_winnings)
            WalletTransaction.objects.create(
                wallet=self.user.wallet,
                amount=self.potential_winnings,
                transaction_type='BET_WON',
                description=f"Won bet ticket #{self.id}"
            )
        elif all(bet.status == 'LOST' for bet in bets):
            self.status = 'LOST'
        elif any(bet.status == 'WON' for bet in bets):
            self.status = 'PARTIAL_WIN'
            if self.bet_type == 'SINGLE':
                winning_bet = next(bet for bet in bets if bet.status == 'WON')
                partial_winnings = winning_bet.amount * winning_bet.market_outcome.odds
            elif self.bet_type == 'MULTIPLE':
                winning_bets = [bet for bet in bets if bet.status == 'WON']
                partial_odds = Decimal('1.000')
                for bet in winning_bets:
                    partial_odds *= bet.market_outcome.odds
                partial_winnings = self.total_stake * partial_odds
            else:  # SYSTEM
                winning_bets = [bet for bet in bets if bet.status == 'WON']
                from itertools import combinations
                partial_winnings = Decimal('0.000')
                for r in range(2, len(winning_bets) + 1):
                    for combo in combinations(winning_bets, r):
                        combo_odds = Decimal('1.000')
                        for bet in combo:
                            combo_odds *= bet.market_outcome.odds
                        partial_winnings += (self.total_stake / len(bets)) * combo_odds

            self.user.wallet.add_funds(partial_winnings)
            WalletTransaction.objects.create(
                wallet=self.user.wallet,
                amount=partial_winnings,
                transaction_type='BET_WON',
                description=f"Partial win on bet ticket #{self.id}"
            )
        elif any(bet.status == 'REFUNDED' for bet in bets):
            self.status = 'REFUNDED'
            self.user.wallet.add_funds(self.total_stake)
            WalletTransaction.objects.create(
                wallet=self.user.wallet,
                amount=self.total_stake,
                transaction_type='BET_REFUNDED',
                description=f"Refunded bet ticket #{self.id}"
            )
        
        self.save()
        return self

    class Meta:
        ordering = ['-created_at']

class Bet(models.Model):
    """
    Bet model to track individual bets on market outcomes.
    """
    BET_STATUS = [
        ('PENDING', 'Pending'),
        ('WON', 'Won'),
        ('LOST', 'Lost'),
        ('REFUNDED', 'Refunded'),
    ]

    ticket = models.ForeignKey(BetTicket, on_delete=models.CASCADE, related_name='bets')
    market_outcome = models.ForeignKey('football_data_app.MarketOutcome', on_delete=models.CASCADE, related_name='bets')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    potential_winnings = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=BET_STATUS, default='PENDING')
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
