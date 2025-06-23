from django.contrib import admin
from .models import PaynowConfig

@admin.register(PaynowConfig)
class PaynowConfigAdmin(admin.ModelAdmin):
    """
    Admin interface for the Paynow Configuration.
    Ensures that only one configuration can be created.
    """
    list_display = ('integration_id', 'api_base_url')
    fieldsets = (
        (None, {
            'fields': ('integration_id', 'integration_key', 'api_base_url'),
            'description': "Enter the API credentials provided by Paynow. There should only be one configuration entry."
        }),
    )

    def has_add_permission(self, request):
        # Allow adding a new config only if one doesn't already exist.
        return not PaynowConfig.objects.exists()
