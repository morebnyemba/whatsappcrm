# whatsappcrm_backend/football_data_app/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'football_data_api'

router = DefaultRouter()
router.register(r'fixtures', views.FixtureViewSet, basename='fixture')
router.register(r'wallet', views.WalletViewSet, basename='wallet')
router.register(r'tickets', views.BetTicketViewSet, basename='ticket')

urlpatterns = [
    path('', include(router.urls)),
]
