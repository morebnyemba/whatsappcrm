# whatsappcrm_backend/customer_data/admin.py
from django.contrib import admin
from .models import CustomerProfile, UserWallet, WalletTransaction, BetTicket, Bet, PendingWithdrawal

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
    list_display = ('id', 'wallet', 'transaction_type', 'amount', 'status', 'payment_method', 'reference', 'external_reference', 'payment_details', 'created_at')
    list_filter = ('transaction_type', 'status', 'payment_method')
    search_fields = ('wallet__user__username', 'reference', 'external_reference', 'description')
    raw_id_fields = ('wallet',)
    readonly_fields = ('created_at', 'external_reference', 'payment_details')
    date_hierarchy = 'created_at' # Add the new action
    actions = ['approve_selected_manual_deposits', 'process_selected_withdrawal_requests']

    def approve_selected_manual_deposits(self, request, queryset):
        """
        Admin action to approve selected PENDING manual deposit transactions.
        """
        from django.contrib import messages
        from customer_data.utils import process_manual_deposit_approval # Import the utility function

        approved_count = 0
        failed_count = 0
        
        for transaction_obj in queryset:
            if transaction_obj.status == 'PENDING' and transaction_obj.payment_method == 'manual' and transaction_obj.transaction_type == 'DEPOSIT':
                result = process_manual_deposit_approval(transaction_obj.reference)
                if result['success']:
                    approved_count += 1
                else:
                    failed_count += 1
                    self.message_user(request, f"Failed to approve transaction {transaction_obj.reference}: {result['message']}", level=messages.ERROR)
            else:
                failed_count += 1
                self.message_user(request, f"Transaction {transaction_obj.reference} is not a PENDING manual deposit and was skipped.", level=messages.WARNING)

        if approved_count > 0:
            self.message_user(request, f"Successfully approved {approved_count} manual deposit(s).", level=messages.SUCCESS)
        if failed_count > 0:
            self.message_user(request, f"Failed to approve {failed_count} transaction(s). Check logs for details.", level=messages.WARNING)

    approve_selected_manual_deposits.short_description = "Approve selected PENDING manual deposits"

    def process_selected_withdrawal_requests(self, request, queryset):
        """
        Admin action to process selected PENDING withdrawal requests.
        """
        from django.contrib import messages
        from customer_data.utils import process_withdrawal_approval # Import the utility function
        
        processed_count = 0
        failed_count = 0
        
        for transaction_obj in queryset:
            if transaction_obj.status == 'PENDING' and transaction_obj.transaction_type == 'WITHDRAWAL':
                # For now, we assume approval. If rejection is needed, a separate action or UI would be required.
                result = process_withdrawal_approval(transaction_obj.reference, approved=True)
                if result['success']:
                    processed_count += 1
                else:
                    failed_count += 1
                    self.message_user(request, f"Failed to process withdrawal {transaction_obj.reference}: {result['message']}", level=messages.ERROR)
            else:
                failed_count += 1
                self.message_user(request, f"Transaction {transaction_obj.reference} is not a PENDING withdrawal request and was skipped.", level=messages.WARNING)

        if processed_count > 0:
            self.message_user(request, f"Successfully processed {processed_count} withdrawal request(s).", level=messages.SUCCESS)
        if failed_count > 0:
            self.message_user(request, f"Failed to process {failed_count} withdrawal request(s). Check logs for details.", level=messages.WARNING)

    process_selected_withdrawal_requests.short_description = "Process selected PENDING withdrawal requests"

@admin.register(PendingWithdrawal)
class PendingWithdrawalAdmin(admin.ModelAdmin):
    """
    Admin interface specifically for Pending Withdrawal requests.
    Uses a proxy model to provide a dedicated view.
    """
    list_display = ('id', 'wallet_user', 'amount', 'payment_method', 'phone_number', 'created_at')
    list_filter = ('payment_method',)
    search_fields = ('wallet__user__username', 'reference', 'payment_details')
    raw_id_fields = ('wallet',)
    readonly_fields = ('created_at', 'reference', 'external_reference', 'payment_details')
    date_hierarchy = 'created_at'
    actions = ['process_selected_withdrawal_requests'] # Reuse the action from WalletTransactionAdmin

    def wallet_user(self, obj):
        return obj.wallet.user.username if obj.wallet and obj.wallet.user else 'N/A'
    wallet_user.short_description = "User"

    def phone_number(self, obj):
        return obj.payment_details.get('phone_number', 'N/A')
    phone_number.short_description = "Phone Number"

    # Ensure the process_selected_withdrawal_requests action is available for this proxy model
    def get_actions(self, request):
        actions = super().get_actions(request)
        # Get the action from WalletTransactionAdmin's instance to ensure it's in the correct format (tuple)
        # We need an instance of WalletTransactionAdmin to call its get_actions method
        # Pass the model and admin.site to the constructor as Django does internally
        wallet_transaction_admin_instance = WalletTransactionAdmin(WalletTransaction, admin.site)
        wt_actions = wallet_transaction_admin_instance.get_actions(request)
        if 'process_selected_withdrawal_requests' in wt_actions:
            actions['process_selected_withdrawal_requests'] = wt_actions['process_selected_withdrawal_requests']
        return actions

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