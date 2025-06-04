# whatsappcrm_backend/whatsappcrm_backend/urls.py
from django.conf.urls.static import static

from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,  # For users to get their access and refresh tokens
    TokenRefreshView,     # For users to refresh their access tokens
    TokenVerifyView,      # Optional: for users/clients to verify a token
)

urlpatterns = [
    # Django Admin interface - useful for backend management via Jazzmin
    path('admin/', admin.site.urls),

    # API endpoints for 'meta_integration' application
    # This includes:
    #   - The webhook receiver for Meta (e.g., /crm-api/meta/webhook/)
    #   - DRF APIs for MetaAppConfig and WebhookEventLog (e.g., /crm-api/meta/api/configs/)
    path('crm-api/meta/', include('meta_integration.urls', namespace='meta_integration_api')), 
    path('crm-api/media/', include('media_manager.urls', namespace='media_asset_api')),
    # API endpoints for 'conversations' application
    # This includes DRF APIs for Contacts and Messages (e.g., /crm-api/conversations/contacts/)
    path('crm-api/conversations/', include('conversations.urls', namespace='conversations_api')),
path('crm-api/customer-data/', include('customer_data.urls', namespace='customer_data_api')),
path('crm-api/stats/', include('stats.urls', namespace='stats_api')),
    # API endpoints for 'flows' application
    # This includes DRF APIs for Flows, FlowSteps, etc. (e.g., /crm-api/flows/flows/)
    path('crm-api/flows/', include('flows.urls', namespace='flows_api')),
    
    # API endpoints for 'customer_data' application (if you add API views to it later)
    # For now, customer_data is primarily managed via the admin and updated by flows.
    # If you need direct API access to CustomerProfile:
    # path('crm-api/customer-data/', include('customer_data.urls', namespace='customer_data_api')),


    # JWT Token Endpoints for authentication from your React Vite frontend
    # Your frontend will POST to 'token_obtain_pair' with username/password
    path('crm-api/auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    # Your frontend will POST to 'token_refresh' with a valid refresh token
    path('crm-api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # Optional: Your frontend can POST to 'token_verify' with a token to check its validity
    path('crm-api/auth/token/verify/', TokenVerifyView.as_view(), name='token_verify'),
path('crm-api/auth/', include('djoser.urls')),
    # DRF's built-in login/logout views for the browsable API.
    # These are helpful for testing your APIs directly in the browser during development.
    # They use SessionAuthentication.
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
]

# Note on Namespaces:
# The 'namespace' argument in include() is useful for URL reversing 
# (e.g., using reverse('meta_integration_api:meta_webhook_receiver') in Python code).
# It helps avoid URL name collisions between apps.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)