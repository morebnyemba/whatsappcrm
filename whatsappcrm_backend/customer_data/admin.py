# whatsappcrm_backend/customer_data/admin.py
from django.contrib import admin
from .models import CustomerProfile, UserWallet, WalletTransaction, BetTicket, Bet

@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    """
    Admin interface for Customer Profiles.
    """
    list_display = ('user', 'contact', 'first_name', 'last_name', 'email', 'updated_at')
    search_fields = ('user__username', 'contact__name', 'contact__whatsapp_id', 'email', 'first_name', 'last_name')
    list_filter = ('acquisition_source',)
    raw_id_fields = ('user', 'contact') # Use raw_id_fields for better performance with many users/contacts
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('User & Contact Links', {'fields': ('user', 'contact')}),
        ('Personal Information', {'fields': ('first_name', 'last_name', 'email', 'gender', 'date_of_birth')}),
        ('Metadata', {'fields': ('acquisition_source', 'created_at', 'updated_at', 'last_updated_from_conversation')}),
    )

@admin.register(UserWallet)
class UserWalletAdmin(admin.ModelAdmin):
    """
    Admin interface for User Wallets.
    """
    list_display = ('user', 'balance', 'updated_at')
    search_fields = ('user__username',)
    raw_id_fields = ('user',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    """
    Admin interface for Wallet Transactions.
    """
    list_display = ('id', 'wallet', 'transaction_type', 'amount', 'status', 'payment_method', 'reference', 'created_at')
    list_filter = ('transaction_type', 'status', 'payment_method')
    search_fields = ('wallet__user__username', 'reference', 'external_reference', 'description')
    raw_id_fields = ('wallet',)
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'

class BetInline(admin.TabularInline):
    """
    Inline for displaying Bets within a BetTicket.
    """
    model = Bet
    extra = 0 # Don't show extra empty forms for new bets
    raw_id_fields = ('market_outcome',)
    readonly_fields = ('potential_winnings', 'created_at', 'updated_at')
    fields = ('market_outcome', 'amount', 'status', 'potential_winnings', 'created_at', 'updated_at')

@admin.register(BetTicket)
class BetTicketAdmin(admin.ModelAdmin):
    """
    Admin interface for Bet Tickets.
    """
    list_display = ('id', 'user', 'total_stake', 'total_odds', 'potential_winnings', 'status', 'bet_type', 'created_at')
    list_filter = ('status', 'bet_type')
    search_fields = ('user__username', 'id')
    raw_id_fields = ('user',)
    inlines = [BetInline]
    readonly_fields = ('created_at', 'updated_at', 'potential_winnings', 'total_odds')

@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    """
    Admin interface for individual Bets.
    """
    list_display = ('id', 'ticket', 'market_outcome', 'amount', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('ticket__user__username', 'ticket__id', 'market_outcome__market__fixture__home_team__name', 'market_outcome__market__fixture__away_team__name')
    raw_id_fields = ('ticket', 'market_outcome')
    readonly_fields = ('created_at', 'updated_at', 'potential_winnings')