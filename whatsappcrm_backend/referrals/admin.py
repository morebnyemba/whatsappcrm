# whatsappcrm_backend/referrals/admin.py
from django.contrib import admin
from .models import ReferralProfile, ReferralSettings

@admin.register(ReferralProfile)
class ReferralProfileAdmin(admin.ModelAdmin):
    """
    Admin view for the ReferralProfile model.
    """
    list_display = ('user', 'referral_code', 'get_referred_by_username', 'referral_bonus_applied')
    search_fields = ('user__username', 'referral_code', 'referred_by__username')
    list_filter = ('referral_bonus_applied',)
    raw_id_fields = ('user', 'referred_by')
    readonly_fields = ('referral_code',)

    @admin.display(description='Referred By')
    def get_referred_by_username(self, obj):
        """
        Displays the username of the referrer for a cleaner list view.
        """
        if obj.referred_by:
            return obj.referred_by.username
        return "N/A"

@admin.register(ReferralSettings)
class ReferralSettingsAdmin(admin.ModelAdmin):
    """
    Admin view for the ReferralSettings singleton model.
    """
    list_display = ('id', 'get_bonus_percentage_display', 'updated_at')

    def get_bonus_percentage_display(self, obj):
        return f"{obj.bonus_percentage_each:.2%}" # Format as percentage
    get_bonus_percentage_display.short_description = "Bonus Percentage (Each)"

    def has_add_permission(self, request):
        return not ReferralSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False