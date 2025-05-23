# media_manager/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MediaAssetViewSet # Import your ViewSet

# Create a router and register our viewsets with it.
router = DefaultRouter()
router.register(r'media-assets', MediaAssetViewSet, basename='mediaasset')
# The `basename` is used for generating URL names. It's good practice to set it,
# especially if your ViewSet doesn't have a `queryset` attribute or if it's dynamic.

urlpatterns = [
    path('', include(router.urls)),
]