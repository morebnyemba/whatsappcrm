# whatsappcrm_backend/meta_integration/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views # Imports from meta_integration/views.py

app_name = 'meta_integration'

# Create a router and register our viewsets with it.
# These ViewSets (MetaAppConfigViewSet, WebhookEventLogViewSet) are defined in meta_integration/views.py
router = DefaultRouter()
router.register(r'configs', views.MetaAppConfigViewSet, basename='metaappconfig')
router.register(r'webhook-logs', views.WebhookEventLogViewSet, basename='webhookeventlog')

# The API URLs are now determined automatically by the router.
# Additionally, we include the original webhook path.
urlpatterns = [
    # Path for Meta to send webhook events to our MetaWebhookAPIView
    # This will be accessed via a URL like: /crm-api/meta/webhook/ (defined in project's urls.py)
    path('webhook/', views.MetaWebhookAPIView.as_view(), name='meta_webhook_receiver'),
    
    # WhatsApp Flows data exchange endpoint
    # This is the endpoint WhatsApp calls when a user interacts with a Flow screen (e.g., login form)
    path('flow-endpoint/', views.WhatsAppFlowEndpointView.as_view(), name='whatsapp_flow_endpoint'),
    
    # Paths for DRF API for managing MetaAppConfig and viewing WebhookEventLog
    # These will be accessible under a prefix like: /crm-api/meta/api/
    # e.g., /crm-api/meta/api/configs/
    # e.g., /crm-api/meta/api/webhook-logs/
    path('api/', include(router.urls)),
]
