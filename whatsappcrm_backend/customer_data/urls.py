# whatsappcrm_backend/customer_data/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerProfileViewSet, PaynowIPNWebhookView

app_name = 'customer_data_api'

router = DefaultRouter()
# This will create URLs like /crm-api/customer-data/profiles/{contact_id}/
# because CustomerProfile's PK is contact_id
router.register(r'profiles', CustomerProfileViewSet, basename='customerprofile')

urlpatterns = [
    path('', include(router.urls)),
    # Add the new webhook URL
    path('paynow/ipn/', PaynowIPNWebhookView.as_view(), name='paynow-ipn-webhook'),
]