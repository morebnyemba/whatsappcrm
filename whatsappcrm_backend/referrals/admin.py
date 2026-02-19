# whatsappcrm_backend/referrals/admin.py
from django.contrib import admin
from .models import ReferralProfile, ReferralSettings, AgentEarning

@admin.register(ReferralProfile)
class ReferralProfileAdmin(admin.ModelAdmin):
    """
    Admin view for the ReferralProfile model (Agent Profile).
    """
    list_display = ('user', 'referral_code', 'get_referred_by_username', 'referral_bonus_applied', 'get_total_earnings')
    search_fields = ('user__username', 'referral_code', 'referred_by__username')
    list_filter = ('referral_bonus_applied',)
    raw_id_fields = ('user', 'referred_by')
    readonly_fields = ('referral_code',)

    @admin.display(description='Referred By (Agent)')
    def get_referred_by_username(self, obj):
        """
        Displays the username of the referrer for a cleaner list view.
        """
        if obj.referred_by:
            return obj.referred_by.username
        return "N/A"

    @admin.display(description='Total Agent Earnings')
    def get_total_earnings(self, obj):
        return f"${obj.total_earnings:.2f}"

@admin.register(AgentEarning)
class AgentEarningAdmin(admin.ModelAdmin):
    """
    Admin view for the AgentEarning model.
    """
    list_display = ('get_agent_username', 'get_referred_username', 'bet_ticket', 'bet_stake', 'commission_percentage_display', 'commission_amount', 'created_at')
    search_fields = ('agent_profile__user__username', 'referred_user__username')
    list_filter = ('created_at',)
    raw_id_fields = ('agent_profile', 'bet_ticket', 'referred_user')
    readonly_fields = ('agent_profile', 'bet_ticket', 'referred_user', 'bet_stake', 'commission_percentage', 'commission_amount', 'created_at')

    @admin.display(description='Agent')
    def get_agent_username(self, obj):
        return obj.agent_profile.user.username

    @admin.display(description='Referred User')
    def get_referred_username(self, obj):
        return obj.referred_user.username

    @admin.display(description='Commission %')
    def commission_percentage_display(self, obj):
        return f"{obj.commission_percentage:.2%}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(ReferralSettings)
class ReferralSettingsAdmin(admin.ModelAdmin):
    """
    Admin view for the ReferralSettings singleton model.
    """
    list_display = ('id', 'get_bonus_percentage_display', 'get_agent_commission_display', 'updated_at')

    def get_bonus_percentage_display(self, obj):
        return f"{obj.bonus_percentage_each:.2%}" # Format as percentage
    get_bonus_percentage_display.short_description = "Bonus Percentage (Each)"

    def get_agent_commission_display(self, obj):
        return f"{obj.agent_commission_percentage:.2%}"
    get_agent_commission_display.short_description = "Agent Commission %"

    def has_add_permission(self, request):
        return not ReferralSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False