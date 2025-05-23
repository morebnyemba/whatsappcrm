# whatsappcrm_backend/flows/admin.py

from django.contrib import admin
from .models import Flow, FlowStep, FlowTransition, ContactFlowState #, MessageTemplate

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
    list_display = ('name', 'description', 'is_active', 'created_at', 'updated_at') # 'app_config',
    search_fields = ('name', 'description')
    list_filter = ('is_active', 'created_at') # 'app_config',
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

