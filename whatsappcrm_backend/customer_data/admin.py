# whatsappcrm_backend/customer_data/admin.py

from django.contrib import admin
from .models import CustomerProfile, UserWallet, WalletTransaction, BetTicket, Bet

@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'date_of_birth', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('user__username', 'user__email', 'phone_number', 'address')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'contact', 'phone_number', 'date_of_birth', 'address')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(UserWallet)
class UserWalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Wallet Information', {
            'fields': ('user', 'balance')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'amount', 'transaction_type', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('wallet__user__username', 'wallet__user__email', 'description')
    readonly_fields = ('created_at',)
    fieldsets = (
        ('Transaction Information', {
            'fields': ('wallet', 'amount', 'transaction_type', 'description')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

@admin.register(BetTicket)
class BetTicketAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_stake', 'total_odds', 'bet_type', 'status', 'created_at')
    list_filter = ('status', 'bet_type', 'created_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Ticket Information', {
            'fields': ('user', 'total_stake', 'potential_winnings', 'status', 'bet_type', 'total_odds')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'market_outcome', 'amount', 'potential_winnings', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('ticket__user__username', 'market_outcome__market__fixture__home_team__name', 'market_outcome__market__fixture__away_team__name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Bet Information', {
            'fields': ('ticket', 'market_outcome', 'amount', 'potential_winnings', 'status')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
