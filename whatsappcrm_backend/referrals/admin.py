# whatsappcrm_backend/referrals/admin.py
from django.contrib import admin
from .models import ReferralProfile

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