# media_manager/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import MediaAsset

@admin.action(description='Sync selected assets with WhatsApp')
def sync_assets_with_whatsapp(modeladmin, request, queryset):
    success_count = 0
    fail_count = 0
    # active_config = None # Fetch active_config once if possible
    # try:
    #     from meta_integration.models import MetaAppConfig
    #     active_config = MetaAppConfig.objects.get_active_config()
    # except Exception:
    #     modeladmin.message_user(request, "Error: Could not retrieve active Meta App Configuration.", level='ERROR')
    #     return

    for asset in queryset:
        # Pass the fetched active_config to avoid fetching it repeatedly in the loop
        # if asset.sync_with_whatsapp(config=active_config):
        if asset.sync_with_whatsapp(): # sync_with_whatsapp will fetch config if not passed
            success_count += 1
        else:
            fail_count += 1
    
    message = f"Attempted sync for {queryset.count()} assets. Successful: {success_count}, Failed: {fail_count}."
    if fail_count > 0:
        modeladmin.message_user(request, message, level='WARNING')
    else:
        modeladmin.message_user(request, message)


class MediaAssetAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'media_type', 'status', 'file_preview',
        'whatsapp_media_id', 'uploaded_to_whatsapp_at', 'file_size_display', 'updated_at'
    )
    list_filter = ('status', 'media_type', 'created_at')
    search_fields = ('name', 'whatsapp_media_id', 'notes', 'file')
    actions = [sync_assets_with_whatsapp]
    readonly_fields = ('file_size', 'mime_type', 'created_at', 'updated_at', 'uploaded_to_whatsapp_at', 'status_display')
    
    fieldsets = (
        (None, {
            'fields': ('name', 'media_type', 'file', 'notes')
        }),
        ('WhatsApp Sync Details (Auto-Managed)', {
            'classes': ('collapse',), # Collapsible section
            'fields': ('status_display', 'whatsapp_media_id', 'mime_type', 'file_size', 'uploaded_to_whatsapp_at'),
        }),
    )

    def file_preview(self, obj):
        if obj.media_type == 'image' and obj.file:
            return format_html('<img src="{}" style="max-height: 50px; max-width: 100px;" />', obj.file.url)
        elif obj.file:
            return obj.file.name.split('/')[-1] # Show filename
        return "No file"
    file_preview.short_description = "Preview/File"

    def file_size_display(self, obj):
        if obj.file_size:
            if obj.file_size < 1024:
                return f"{obj.file_size} B"
            elif obj.file_size < 1024 * 1024:
                return f"{obj.file_size / 1024:.1f} KB"
            else:
                return f"{obj.file_size / (1024 * 1024):.1f} MB"
        return "-"
    file_size_display.short_description = "Size"

    def status_display(self, obj):
        return obj.get_status_display()
    status_display.short_description = "Current Status"


admin.site.register(MediaAsset, MediaAssetAdmin)