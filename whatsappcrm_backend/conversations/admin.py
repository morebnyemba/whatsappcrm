# whatsappcrm_backend/conversations/admin.py

from django.contrib import admin
from .models import Contact, Message, ContactSession

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('whatsapp_id', 'name', 'first_seen', 'last_seen', 'is_blocked') # Add 'associated_app_config_name' if using the FK
    search_fields = ('whatsapp_id', 'name')
    list_filter = ('is_blocked', 'last_seen', 'first_seen') # Add 'associated_app_config' if using the FK
    readonly_fields = ('first_seen', 'last_seen')
    # fieldsets = (
    #     (None, {'fields': ('whatsapp_id', 'name', 'is_blocked')}),
    #     # ('Association', {'fields': ('associated_app_config',)}), # If using the FK
    #     # ('Details', {'fields': ('custom_fields',)}),
    #     ('Timestamps', {'fields': ('first_seen', 'last_seen'), 'classes': ('collapse',)}),
    # )

    # def associated_app_config_name(self, obj):
    #     return obj.associated_app_config.name if obj.associated_app_config else "N/A"
    # associated_app_config_name.short_description = "App Config"


class MessageInline(admin.TabularInline): # Or admin.StackedInline for a different layout
    model = Message
    fields = ('timestamp', 'direction', 'message_type', 'text_content_preview', 'status', 'wamid')
    readonly_fields = ('timestamp', 'direction', 'message_type', 'text_content_preview', 'status', 'wamid')
    extra = 0 # Don't show extra empty forms for adding messages here
    can_delete = False # Usually don't want to delete messages from contact view
    show_change_link = True # Link to the full message change form
    ordering = ('-timestamp',) # Show latest messages first in the inline

    def text_content_preview(self, obj):
        if obj.text_content:
            return (obj.text_content[:75] + '...') if len(obj.text_content) > 75 else obj.text_content
        if obj.message_type != 'text' and isinstance(obj.content_payload, dict):
            # For non-text, show a snippet of the payload keys or type
            if obj.message_type == 'interactive' and obj.content_payload.get('type'):
                return f"Interactive: {obj.content_payload.get('type')}"
            return f"({obj.message_type})"
        return "N/A"
    text_content_preview.short_description = "Content Preview"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'contact_link', 'direction', 'message_type', 'status', 'timestamp', 'wamid_short')
    list_filter = ('timestamp', 'direction', 'message_type', 'status', 'contact__name') # Add 'app_config' if using the FK
    search_fields = ('wamid', 'text_content', 'contact__whatsapp_id', 'contact__name', 'content_payload') # Be careful with JSON search
    readonly_fields = ('contact', 'wamid', 'direction', 'message_type', 'content_payload', 'timestamp', 'status_timestamp', 'error_details') # 'app_config'
    date_hierarchy = 'timestamp'
    list_per_page = 25
    fieldsets = (
        ('Message Info', {'fields': ('contact', 'direction', 'message_type', 'timestamp')}), # 'app_config'
        ('Content', {'fields': ('wamid', 'text_content', 'content_payload')}),
        ('Status & Delivery', {'fields': ('status', 'status_timestamp', 'error_details')}),
        ('Internal', {'fields': ('is_internal_note',)}),
    )

    def contact_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if obj.contact:
            link = reverse("admin:conversations_contact_change", args=[obj.contact.id])
            return format_html('<a href="{}">{}</a>', link, obj.contact)
        return "N/A"
    contact_link.short_description = "Contact"

    def wamid_short(self, obj):
        if obj.wamid:
            return (obj.wamid[:20] + '...') if len(obj.wamid) > 20 else obj.wamid
        return "N/A"
    wamid_short.short_description = "WAMID"

    def get_queryset(self, request):
        # Optimize query by prefetching related Contact
        return super().get_queryset(request).select_related('contact') # 'app_config'


@admin.register(ContactSession)
class ContactSessionAdmin(admin.ModelAdmin):
    list_display = ('contact', 'is_authenticated', 'authenticated_at', 'expires_at', 'last_activity_at')
    search_fields = ('contact__whatsapp_id', 'contact__name')
    list_filter = ('is_authenticated',)
    readonly_fields = ('contact', 'authenticated_at', 'last_activity_at')
    list_select_related = ('contact',)
