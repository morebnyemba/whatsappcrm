from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'wallet', views.WalletViewSet, basename='wallet')
router.register(r'bets', views.BetViewSet, basename='bet')

urlpatterns = [
    path('', include(router.urls)),
] 