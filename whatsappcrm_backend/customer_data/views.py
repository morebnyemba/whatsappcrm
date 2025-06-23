# whatsappcrm_backend/customer_data/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.http import Http404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator


from .models import CustomerProfile
from .serializers import CustomerProfileSerializer
from conversations.models import Contact # To ensure contact exists for profile creation/retrieval
from .utils import process_paynow_ipn

import logging
logger = logging.getLogger(__name__)

class IsAdminOrUpdateOnly(permissions.BasePermission): # Example, adjust as needed
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_staff

class CustomerProfileViewSet(viewsets.ModelViewSet):
    queryset = CustomerProfile.objects.select_related('contact').all()
    serializer_class = CustomerProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrUpdateOnly]
    
    # CustomerProfile's PK is contact_id
    # DRF ModelViewSet will use 'pk' from URL by default.
    # Since CustomerProfile.pk IS contact_id, this works.
    # If you want the URL to explicitly say /profiles/{contact_pk}/
    # you might need to adjust lookup_field or URL regex slightly
    # but /profiles/{pk}/ where pk is contact_id is fine.

    def get_object(self):
        """
        Override get_object to use the PK from the URL, which is the contact_id.
        If the profile doesn't exist for a GET/PUT/PATCH, create it on-the-fly.
        """
        queryset = self.filter_queryset(self.get_queryset())
        pk = self.kwargs.get(self.lookup_url_kwarg or 'pk') # Default lookup is 'pk'

        try:
            obj = queryset.get(pk=pk) # pk here is contact_id
            self.check_object_permissions(self.request, obj)
            return obj
        except CustomerProfile.DoesNotExist:
            # If profile doesn't exist but contact does, create profile for GET/PUT/PATCH.
            if self.request.method in ['GET', 'PUT', 'PATCH']:
                contact = get_object_or_404(Contact, pk=pk) # Check if contact exists
                obj, created = CustomerProfile.objects.get_or_create(contact=contact)
                if created:
                    logger.info(f"CustomerProfile created on-the-fly for Contact ID: {pk} during {self.request.method} action.")
                self.check_object_permissions(self.request, obj)
                return obj
            raise Http404("CustomerProfile not found and action is not retrieve/update.")

    def perform_update(self, serializer):
        # Set last_updated_from_conversation when an agent/API updates the profile
        serializer.save(last_updated_from_conversation=timezone.now())
        logger.info(f"CustomerProfile for Contact ID {serializer.instance.contact_id} updated by {self.request.user}.")

    # perform_create is usually not needed for a OneToOneProfile that's auto-created
    # or created on first update/get. If you want an explicit POST to /profiles/
    # to create one (expecting contact_id in payload), that's also possible.
    # The get_or_create in get_object handles on-demand creation for GET/PUT/PATCH.

@method_decorator(csrf_exempt, name='dispatch')
class PaynowIPNWebhookView(APIView):
    """
    Receives Instant Payment Notifications (IPN) from Paynow.
    This endpoint should be publicly accessible.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        # Paynow sends data as form-urlencoded
        ipn_data = request.data.dict()
        logger.info(f"Received Paynow IPN webhook request. Data: {ipn_data}")

        # Offload processing to a utility function
        result = process_paynow_ipn(ipn_data)

        if result["success"]:
            # Paynow expects an empty 200 OK to acknowledge receipt.
            return Response(status=status.HTTP_200_OK)
        else:
            # Even on failure, we return 200 OK so Paynow doesn't keep retrying.
            # The error is logged on our side for investigation.
            logger.error(f"Failed to process Paynow IPN. Reason: {result['message']}. Data: {ipn_data}")
            return Response(status=status.HTTP_200_OK)