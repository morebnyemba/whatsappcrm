# whatsappcrm_backend/flows/admin.py

from django.contrib import admin
from .models import Flow, FlowStep, FlowTransition, ContactFlowState, WhatsAppFlow, WhatsAppFlowResponse

# @admin.register(MessageTemplate)
# class MessageTemplateAdmin(admin.ModelAdmin):
#     list_display = ('name', 'created_at', 'updated_at') # 'app_config',
#     search_fields = ('name',)
#     # list_filter = ('app_config',)


class FlowStepInline(admin.TabularInline): # Or StackedInline
    model = FlowStep
    fields = ('name', 'step_type', 'is_entry_point', 'config')
    extra = 1
    show_change_link = True
    ordering = ('is_entry_point', 'name',) # Show entry point first

@admin.register(Flow)
class FlowAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'is_active', 'requires_login', 'created_at', 'updated_at') # 'app_config',
    search_fields = ('name', 'description')
    list_filter = ('is_active', 'requires_login', 'created_at') # 'app_config',
    inlines = [FlowStepInline]
    actions = ['activate_flows', 'deactivate_flows']

    def activate_flows(self, request, queryset):
        queryset.update(is_active=True)
    activate_flows.short_description = "Activate selected flows"

    def deactivate_flows(self, request, queryset):
        queryset.update(is_active=False)
    deactivate_flows.short_description = "Deactivate selected flows"


class FlowTransitionInline(admin.TabularInline):
    model = FlowTransition
    fk_name = 'current_step' # Explicitly define the foreign key to FlowStep
    fields = ('next_step', 'condition_config', 'priority')
    extra = 1
    show_change_link = True
    ordering = ('priority',)

@admin.register(FlowStep)
class FlowStepAdmin(admin.ModelAdmin):
    list_display = ('name', 'flow_name', 'step_type', 'is_entry_point', 'created_at')
    search_fields = ('name', 'flow__name', 'config')
    list_filter = ('flow', 'step_type', 'is_entry_point')
    inlines = [FlowTransitionInline]
    list_select_related = ('flow',) # Optimize query

    def flow_name(self, obj):
        return obj.flow.name
    flow_name.short_description = "Flow"
    flow_name.admin_order_field = 'flow__name'


@admin.register(FlowTransition)
class FlowTransitionAdmin(admin.ModelAdmin):
    list_display = ('id', 'current_step_name', 'next_step_name', 'priority', 'condition_summary')
    search_fields = ('current_step__name', 'next_step__name', 'condition_config')
    list_filter = ('current_step__flow', 'priority') # Filter by flow via current_step
    list_select_related = ('current_step', 'next_step', 'current_step__flow') # Optimize queries

    def current_step_name(self, obj):
        return f"{obj.current_step.name} (Flow: {obj.current_step.flow.name})"
    current_step_name.short_description = "From Step"

    def next_step_name(self, obj):
        return obj.next_step.name
    next_step_name.short_description = "To Step"
    
    def condition_summary(self, obj):
        condition_type = obj.condition_config.get('type', 'N/A')
        if condition_type == 'always_true':
            return "Always"
        elif condition_type == 'user_reply_matches':
            return f"Reply matches: '{obj.condition_config.get('keyword', '')}'"
        elif condition_type == 'interactive_reply_id_equals':
            return f"Interactive ID: '{obj.condition_config.get('reply_id', '')}'"
        # Add more summaries for other condition types
        return condition_type if condition_type != 'N/A' else "Custom"
    condition_summary.short_description = "Condition"


@admin.register(ContactFlowState)
class ContactFlowStateAdmin(admin.ModelAdmin):
    list_display = ('contact', 'current_flow_name', 'current_step_name', 'last_updated_at')
    search_fields = ('contact__whatsapp_id', 'contact__name', 'current_flow__name', 'current_step__name')
    list_filter = ('current_flow', 'current_step__step_type', 'last_updated_at')
    readonly_fields = ('contact', 'current_flow', 'current_step', 'flow_context_data', 'started_at', 'last_updated_at')
    list_select_related = ('contact', 'current_flow', 'current_step') # Optimize queries

    def current_flow_name(self, obj):
        return obj.current_flow.name
    current_flow_name.short_description = "Current Flow"

    def current_step_name(self, obj):
        return obj.current_step.name
    current_step_name.short_description = "Current Step"


@admin.register(WhatsAppFlow)
class WhatsAppFlowAdmin(admin.ModelAdmin):
    list_display = ('friendly_name', 'name', 'sync_status', 'flow_id', 'is_active', 'version', 'last_synced_at')
    search_fields = ('name', 'friendly_name', 'flow_id', 'description')
    list_filter = ('sync_status', 'is_active', 'meta_app_config', 'created_at')
    readonly_fields = ('flow_id', 'created_at', 'updated_at', 'last_synced_at', 'sync_error')
    list_select_related = ('meta_app_config', 'flow_definition')

    fieldsets = (
        (None, {
            'fields': ('name', 'friendly_name', 'description', 'is_active')
        }),
        ('Meta Integration', {
            'fields': ('meta_app_config', 'flow_id', 'sync_status', 'sync_error', 'last_synced_at')
        }),
        ('Flow Configuration', {
            'fields': ('flow_json', 'version', 'flow_definition'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['sync_with_meta', 'publish_flows', 'activate_flows', 'deactivate_flows']

    def sync_with_meta(self, request, queryset):
        from flows.whatsapp_flow_service import WhatsAppFlowService

        synced = 0
        errors = []

        for flow in queryset:
            try:
                service = WhatsAppFlowService(flow.meta_app_config)
                if service.sync_flow(flow):
                    synced += 1
                else:
                    errors.append(f"{flow.name}: {flow.sync_error}")
            except Exception as e:
                errors.append(f"{flow.name}: {str(e)}")

        if synced:
            self.message_user(request, f"Successfully synced {synced} flow(s)")
        if errors:
            self.message_user(request, f"Errors: {', '.join(errors)}", level='error')

    sync_with_meta.short_description = "Sync selected flows with Meta"

    def publish_flows(self, request, queryset):
        from flows.whatsapp_flow_service import WhatsAppFlowService

        published = 0
        errors = []

        for flow in queryset:
            if not flow.flow_id:
                errors.append(f"{flow.name}: No flow_id, sync first")
                continue

            try:
                service = WhatsAppFlowService(flow.meta_app_config)
                if service.publish_flow(flow):
                    published += 1
                else:
                    errors.append(f"{flow.name}: {flow.sync_error}")
            except Exception as e:
                errors.append(f"{flow.name}: {str(e)}")

        if published:
            self.message_user(request, f"Successfully published {published} flow(s)")
        if errors:
            self.message_user(request, f"Errors: {', '.join(errors)}", level='error')

    publish_flows.short_description = "Publish selected flows"

    def activate_flows(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"Activated {queryset.count()} flow(s)")

    activate_flows.short_description = "Activate selected flows"

    def deactivate_flows(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {queryset.count()} flow(s)")

    deactivate_flows.short_description = "Deactivate selected flows"


@admin.register(WhatsAppFlowResponse)
class WhatsAppFlowResponseAdmin(admin.ModelAdmin):
    list_display = ('id', 'whatsapp_flow_name', 'contact_display', 'is_processed', 'created_at', 'processed_at')
    search_fields = ('contact__whatsapp_id', 'contact__name', 'whatsapp_flow__name', 'flow_token')
    list_filter = ('is_processed', 'whatsapp_flow', 'created_at')
    readonly_fields = ('whatsapp_flow', 'contact', 'flow_token', 'response_data', 'created_at', 'processed_at')
    list_select_related = ('whatsapp_flow', 'contact')

    fieldsets = (
        ('Flow Response', {
            'fields': ('whatsapp_flow', 'contact', 'flow_token', 'response_data')
        }),
        ('Processing', {
            'fields': ('is_processed', 'processing_notes', 'processed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_processed', 'mark_as_unprocessed']

    def whatsapp_flow_name(self, obj):
        return obj.whatsapp_flow.friendly_name or obj.whatsapp_flow.name
    whatsapp_flow_name.short_description = "Flow"

    def contact_display(self, obj):
        return f"{obj.contact.name or obj.contact.whatsapp_id}"
    contact_display.short_description = "Contact"

    def mark_as_processed(self, request, queryset):
        from django.utils import timezone
        queryset.update(is_processed=True, processed_at=timezone.now())
        self.message_user(request, f"Marked {queryset.count()} response(s) as processed")

    mark_as_processed.short_description = "Mark as processed"

    def mark_as_unprocessed(self, request, queryset):
        queryset.update(is_processed=False, processed_at=None)
        self.message_user(request, f"Marked {queryset.count()} response(s) as unprocessed")

    mark_as_unprocessed.short_description = "Mark as unprocessed"

