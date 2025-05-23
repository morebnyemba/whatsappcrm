# whatsappcrm_backend/conversations/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views # Import from the single views.py in the current app

app_name = 'conversations'

router = DefaultRouter()
# Registering the ViewSets defined in conversations/views.py
router.register(r'contacts', views.ContactViewSet, basename='contact')
router.register(r'messages', views.MessageViewSet, basename='message')

urlpatterns = [
    path('', include(router.urls)),
    # This will create URLs like:
    # /crm-api/conversations/contacts/
    # /crm-api/conversations/contacts/{id}/
    # /crm-api/conversations/contacts/{id}/messages/ (custom action)
    # /crm-api/conversations/contacts/{id}/toggle-block/ (custom action)
    # /crm-api/conversations/messages/
    # /crm-api/conversations/messages/{id}/
]
