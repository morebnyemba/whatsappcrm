# whatsappcrm_backend/customer_data/admin.py

from django.contrib import admin
from .models import CustomerProfile

@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = (
        'contact_whatsapp_id', 
        'get_profile_full_name', # Use the method for display
        'email', 
        'company_name',
        'lifecycle_stage',
        'contact_first_interaction_at',
        'last_updated_from_conversation',
        'updated_at',
    )
    search_fields = (
        'contact__whatsapp_id', 
        'contact__name', 
        'first_name', 
        'last_name', 
        'email', 
        'company_name',
        'preferences', 
        'custom_attributes',
        'tags'
    )
    list_filter = (
        'lifecycle_stage', 
        'contact__first_seen', 
        'last_updated_from_conversation', 
        'updated_at',
        'country', # Added country for filtering
        'gender',
    )
    readonly_fields = (
        'contact', 
        'created_at', 
        'updated_at', 
        'contact_first_interaction_at'
    ) 

    fieldsets = (
        (None, {'fields': ('contact',)}),
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'email', 'secondary_phone_number', 'date_of_birth', 'gender')
        }),
        ('Professional Information', {
            'fields': ('company_name', 'job_title')
        }),
        ('Location Information', {
            'fields': ('address_line_1', 'address_line_2', 'city', 'state_province', 'postal_code', 'country')
        }),
        ('CRM & Engagement Data', {
            'fields': ('lifecycle_stage', 'acquisition_source', 'tags', 'notes')
        }),
        ('Collected Flow Data (JSON)', {
            'fields': ('preferences', 'custom_attributes'),
            'classes': ('collapse',), # Keep JSON fields collapsible
        }),
        ('Timestamps', {
            'fields': (
                'contact_first_interaction_at', 
                'created_at', 
                'updated_at', 
                'last_updated_from_conversation'
            ), 
            'classes': ('collapse',)
        }),
    )

    def contact_whatsapp_id(self, obj):
        return obj.contact.whatsapp_id
    contact_whatsapp_id.short_description = "WhatsApp ID"
    contact_whatsapp_id.admin_order_field = 'contact__whatsapp_id'

    def get_profile_full_name(self, obj):
        name = obj.get_full_name()
        return name if name else (obj.contact.name or '-') # Fallback to contact name
    get_profile_full_name.short_description = "Profile Name"
    get_profile_full_name.admin_order_field = 'last_name' # Example: sort by last_name

    def contact_first_interaction_at(self, obj):
        if obj.contact:
            return obj.contact.first_seen
        return None
    contact_first_interaction_at.short_description = "Conversation Initiated"
    contact_first_interaction_at.admin_order_field = 'contact__first_seen'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('contact')
