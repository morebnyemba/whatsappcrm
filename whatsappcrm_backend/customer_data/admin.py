# whatsappcrm_backend/customer_data/admin.py
from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone
from .models import CustomerProfile, UserWallet, WalletTransaction, BetTicket, Bet, PendingWithdrawal
from .utils import process_manual_deposit_approval, process_withdrawal_approval
from football_data_app.models import FootballFixture
from football_data_app.tasks import settle_fixture_pipeline_task

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
    date_hierarchy = 'created_at'
    actions = ['approve_selected_manual_deposits', 'approve_selected_withdrawal_requests', 'reject_selected_withdrawal_requests']

    def _process_transactions(self, request, queryset, action_name, process_func, filter_kwargs, success_message, **process_kwargs):
        """
        Generic helper to process transactions, reducing code duplication in admin actions.
        """
        valid_transactions = queryset.filter(**filter_kwargs)
        
        processed_count = 0
        failed_count = 0
        
        for transaction_obj in valid_transactions:
            result = process_func(transaction_obj.reference, **process_kwargs)
            if result['success']:
                processed_count += 1
            else:
                failed_count += 1
                messages.error(request, f"Failed to {action_name} transaction {transaction_obj.reference}: {result['message']}")

        skipped_count = queryset.exclude(pk__in=valid_transactions.values_list('pk', flat=True)).count()
        if skipped_count > 0:
            messages.warning(request, f"{skipped_count} selected transaction(s) were skipped as they did not meet the criteria for this action.")

        if processed_count > 0:
            messages.success(request, success_message.format(count=processed_count))
        if failed_count > 0:
            messages.warning(request, f"Failed to {action_name} {failed_count} transaction(s). Check individual messages and logs for details.")

    def approve_selected_manual_deposits(self, request, queryset):
        """
        Admin action to approve selected PENDING manual deposit transactions.
        """
        self._process_transactions(
            request=request,
            queryset=queryset,
            action_name="approve manual deposit",
            process_func=process_manual_deposit_approval,
            filter_kwargs={
                'status': 'PENDING',
                'payment_method': 'manual',
                'transaction_type': 'DEPOSIT'
            },
            success_message="Successfully approved {count} manual deposit(s)."
        )
    approve_selected_manual_deposits.short_description = "Approve selected PENDING manual deposits"

    def approve_selected_withdrawal_requests(self, request, queryset):
        """
        Admin action to APPROVE selected PENDING withdrawal requests.
        """
        self._process_transactions(
            request=request,
            queryset=queryset,
            action_name="approve withdrawal",
            process_func=process_withdrawal_approval,
            filter_kwargs={'status': 'PENDING', 'transaction_type': 'WITHDRAWAL'},
            success_message="Successfully approved {count} withdrawal request(s).",
            approved=True
        )
    approve_selected_withdrawal_requests.short_description = "Approve selected PENDING withdrawals"

    def reject_selected_withdrawal_requests(self, request, queryset):
        """
        Admin action to REJECT selected PENDING withdrawal requests.
        """
        self._process_transactions(
            request=request,
            queryset=queryset,
            action_name="reject withdrawal",
            process_func=process_withdrawal_approval,
            filter_kwargs={'status': 'PENDING', 'transaction_type': 'WITHDRAWAL'},
            success_message="Successfully rejected {count} withdrawal request(s).",
            approved=False,
            reason="Rejected by admin action."
        )
    reject_selected_withdrawal_requests.short_description = "Reject selected PENDING withdrawals"

@admin.register(PendingWithdrawal)
class PendingWithdrawalAdmin(WalletTransactionAdmin):
    """
    Admin interface specifically for Pending Withdrawal requests.
    Inherits from WalletTransactionAdmin to reuse actions and basic setup,
    but provides a focused view for pending withdrawals via the proxy model.
    """
    list_display = ('id', 'wallet_user', 'amount', 'payment_method', 'phone_number', 'created_at')
    list_filter = ('payment_method',)
    search_fields = ('wallet__user__username', 'reference', 'payment_details')

    def wallet_user(self, obj):
        return obj.wallet.user.username if obj.wallet and obj.wallet.user else 'N/A'
    wallet_user.short_description = "User"

    def phone_number(self, obj):
        # Ensure payment_details is a dict before calling .get()
        if isinstance(obj.payment_details, dict):
            return obj.payment_details.get('phone_number', 'N/A')
        return 'N/A'
    phone_number.short_description = "Phone Number"

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
    actions = ['force_settle_tickets']
    list_select_related = ('user',)

    @admin.action(description="Force settle selected PENDING tickets")
    def force_settle_tickets(self, request, queryset):
        pending_tickets = queryset.filter(status='PENDING')
        fixtures_to_settle_ids = set()

        # Find all unique fixtures linked to the pending bets in the selected tickets
        fixtures = FootballFixture.objects.filter(
            markets__outcomes__bets__ticket__in=pending_tickets,
            markets__outcomes__bets__status='PENDING'
        ).distinct()

        settled_fixture_count = 0
        with transaction.atomic():
            for fixture in fixtures:
                if fixture.status != FootballFixture.FixtureStatus.FINISHED:
                    fixture.status = FootballFixture.FixtureStatus.FINISHED
                    if fixture.home_team_score is None: fixture.home_team_score = 0
                    if fixture.away_team_score is None: fixture.away_team_score = 0
                    fixture.last_score_update = timezone.now()
                    fixture.save(update_fields=['status', 'home_team_score', 'away_team_score', 'last_score_update'])
                    settled_fixture_count += 1
                fixtures_to_settle_ids.add(fixture.id)

        for fixture_id in fixtures_to_settle_ids:
            settle_fixture_pipeline_task.delay(fixture_id)

        if settled_fixture_count > 0:
            self.message_user(request, f"Forced {settled_fixture_count} fixtures to FINISHED status.")
        
        if fixtures_to_settle_ids:
            self.message_user(request, f"Dispatched settlement pipelines for {len(fixtures_to_settle_ids)} unique fixtures. Check Celery logs for progress.")
        else:
            self.message_user(request, "No pending bets found in the selected tickets, or their fixtures are already settled.", level=messages.WARNING)

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