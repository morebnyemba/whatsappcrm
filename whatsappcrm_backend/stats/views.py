# whatsappcrm_backend/stats/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.utils import timezone
from datetime import timedelta # Removed 'date' as it's not used directly here
from django.db.models import Count, Avg, Q
from django.db.models.functions import TruncDate

# Import models from your other apps
from conversations.models import Contact, Message
from flows.models import Flow # Removed FlowStep, ContactFlowState unless specifically needed for a stat here
from meta_integration.models import MetaAppConfig

import logging
logger = logging.getLogger(__name__)

class DashboardSummaryStatsAPIView(APIView):
    """
    API View to provide a summary of statistics for the dashboard.
    All timestamp comparisons are timezone-aware.
    """
    permission_classes = [permissions.IsAuthenticated] # Or IsAdminUser if preferred

    def get(self, request, format=None):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        twenty_four_hours_ago = now - timedelta(hours=24)
        seven_days_ago_start_of_day = today_start - timedelta(days=6)

        # --- Calculate Stats ---

        # MetaAppConfig Stats
        meta_configs_total = MetaAppConfig.objects.count()
        active_meta_config_obj = MetaAppConfig.objects.filter(is_active=True).first()
        active_meta_config_name = active_meta_config_obj.name if active_meta_config_obj else None
        
        # Flow Stats
        active_flows_count = Flow.objects.filter(is_active=True).count()
        total_flows_count = Flow.objects.count()
        avg_steps_data = Flow.objects.annotate(num_steps=Count('steps')).filter(num_steps__gt=0).aggregate(avg_val=Avg('num_steps'))
        avg_steps_per_flow = round(avg_steps_data['avg_val'], 1) if avg_steps_data['avg_val'] else 0.0

        # Contact Stats
        # CORRECTED: Use 'first_seen' instead of 'created_at'
        new_contacts_today_count = Contact.objects.filter(
            first_seen__gte=today_start, 
            first_seen__lte=today_end
        ).count()
        total_contacts_count = Contact.objects.count()
        # Uses 'needs_human_intervention' which should now exist on Contact model
        pending_human_intervention_count = Contact.objects.filter(needs_human_intervention=True).count()

        # Message Stats
        messages_sent_24h_count = Message.objects.filter(
            direction='out', 
            timestamp__gte=twenty_four_hours_ago
        ).count()
        messages_received_24h_count = Message.objects.filter(
            direction='in',
            timestamp__gte=twenty_four_hours_ago
        ).count()


        # Active Conversations (Example: unique contacts with any message in the last 4 hours)
        four_hours_ago = now - timedelta(hours=4)
        active_conversations_count = Message.objects.filter(
            timestamp__gte=four_hours_ago
        ).values('contact_id').distinct().count()
        # Alternative: Count contacts currently in any flow state
        # from flows.models import ContactFlowState
        # active_conversations_in_flow_count = ContactFlowState.objects.count()


        # Flow Completions Today (Conceptual - requires your app to define what a "completion" is)
        # E.g., if reaching certain 'end_flow' steps marks completion and you log it.
        flow_completions_today_count = 0 # Placeholder - Replace with your actual query

        # --- Prepare Chart Data (Conceptual Examples) ---

        # Conversation Trends Data: Messages per day for the last 7 days
        # This query groups messages by date and counts them.
        message_trends = Message.objects.filter(timestamp__gte=seven_days_ago_start_of_day)\
            .annotate(date=TruncDate('timestamp'))\
            .values('date')\
            .annotate(incoming_count=Count('id', filter=Q(direction='in')),
                      outgoing_count=Count('id', filter=Q(direction='out')))\
            .order_by('date')
        
        conversation_trends_data = [
            {
                "date": item['date'].strftime('%Y-%m-%d'), 
                "incoming_messages": item['incoming_count'],
                "outgoing_messages": item['outgoing_count'],
                "total_messages": item['incoming_count'] + item['outgoing_count']
            }
            for item in message_trends
        ]

        # Bot Performance Data (Conceptual - needs specific metrics from your system)
        bot_performance_data = {
            "automated_resolution_rate": 0.0, # Example: (flows_completed_without_handover / total_flows_started)
            "avg_bot_response_time_seconds": 0.0, # Needs tracking bot response times
            "total_incoming_messages_processed": Message.objects.filter(direction='in').count(),
        }
        # You would need more detailed logic and potentially logging to calculate these accurately.

        # --- Recent Activity (Simplified Example) ---
        # Fetches last 3 new contacts and last 2 updated flows as "activity"
        # For a real system, a dedicated ActivityLog model is better.
        recent_new_contacts = Contact.objects.order_by('-first_seen')[:3] # Use first_seen
        recent_updated_flows = Flow.objects.order_by('-updated_at')[:2]
        
        activity_log_for_frontend = []
        for contact_activity in recent_new_contacts:
            activity_log_for_frontend.append({
                "id": f"contact_new_{contact_activity.id}",
                "text": f"New contact: {contact_activity.name or contact_activity.whatsapp_id}",
                "timestamp": contact_activity.first_seen.isoformat(), # Use first_seen
                "iconName": "FiUsers", 
                "iconColor": "text-emerald-500"
            })
        for flow_activity in recent_updated_flows:
            activity_log_for_frontend.append({
                "id": f"flow_update_{flow_activity.id}",
                "text": f"Flow '{flow_activity.name}' was updated.",
                "timestamp": flow_activity.updated_at.isoformat(),
                "iconName": "FiZap", 
                "iconColor": "text-purple-500"
            })
        # Sort combined activities by timestamp descending for display
        activity_log_for_frontend.sort(key=lambda x: x['timestamp'], reverse=True)


        # --- Assemble Response ---
        data = {
            'stats_cards': { # Data for the top summary cards
                'active_conversations_count': active_conversations_count,
                'new_contacts_today': new_contacts_today_count,
                'total_contacts': total_contacts_count,
                'messages_sent_24h': messages_sent_24h_count,
                'messages_received_24h': messages_received_24h_count, # Added this
                'meta_configs_total': meta_configs_total,
                'meta_config_active_name': active_meta_config_name,
                'pending_human_handovers': pending_human_intervention_count,
            },
            'flow_insights': { # Data for the "Flow Insights" section
                'active_flows_count': active_flows_count,
                'total_flows_count': total_flows_count,
                'flow_completions_today': flow_completions_today_count, # Placeholder
                'avg_steps_per_flow': avg_steps_per_flow,
            },
            'charts_data': { # Data for charts
                'conversation_trends': conversation_trends_data,
                'bot_performance': bot_performance_data, # Placeholder
            },
            'recent_activity_log': activity_log_for_frontend[:5], # Show latest 5 activities
            'system_status': 'Operational' # This could be dynamic based on other checks
        }

        return Response(data, status=status.HTTP_200_OK)

# You can add other specific stat views here if needed, e.g.:
# class RecentActivitiesAPIView(APIView): ...
# class ConversationTrendDataAPIView(APIView): ...