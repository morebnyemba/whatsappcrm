from django.urls import path
from . import views

urlpatterns = [
    # URL for Paynow to redirect the user's browser after payment
    path('paynow/return/', views.paynow_return_view, name='paynow_return'),
    # URL for Paynow to send server-to-server IPN (Instant Payment Notification)
    path('paynow/result/', views.paynow_result_view, name='paynow_result'),
]
