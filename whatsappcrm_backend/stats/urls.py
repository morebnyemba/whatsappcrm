# stats/urls.py
from django.urls import path
from .views import DashboardSummaryStatsAPIView

app_name = 'stats_api'

urlpatterns = [
    path('summary/', DashboardSummaryStatsAPIView.as_view(), name='dashboard_summary_stats'),
    # You can add more specific stat endpoints here if needed later
]