from django.urls import path
from .views import paynow_return_view

app_name = 'paynow_integration'

urlpatterns = [
    path('return/', paynow_return_view, name='paynow-return'),
]
