# whatsappcrm_backend/conversations/views.py

from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Prefetch
from django.utils import timezone
from django.shortcuts import get_object_or_404
import logging # Make sure logging is imported

from .models import Contact, Message
from .serializers import (
    ContactSerializer,
    MessageSerializer,
    MessageListSerializer,
    ContactDetailSerializer,
)
# For dispatching Celery task
from meta_integration.tasks import send_whatsapp_message_task
# To get active MetaAppConfig for sending
from meta_integration.models import MetaAppConfig # Or use your helper function like get_active_meta_config from meta_integration.views

logger = logging.getLogger(__name__) # Standard way to get logger for current module

# Define permissions if not already in a central place
class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow admin users to edit objects.
    Others can only read. Assumes IsAuthenticated is also applied.
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS: # GET, HEAD, OPTIONS
            return True
        return request.user and request.user.is_staff


class ContactViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Contacts.
    - Admins can CRUD.
    - Authenticated users can list/retrieve (permissions can be refined).
    """
    queryset = Contact.objects.all().order_by('-last_seen')
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ContactDetailSerializer
        return ContactSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        # Added search capability from your original file
        search_term = self.request.query_params.get('search', None)
        if search_term:
            queryset = queryset.filter(
                Q(name__icontains=search_term) | 
                Q(whatsapp_id__icontains=search_term)
            )
        
        # Added filter for needs_human_intervention from your original file
        needs_intervention_filter = self.request.query_params.get('needs_human_intervention', None)
        if needs_intervention_filter is not None:
            if needs_intervention_filter.lower() == 'true':
                queryset = queryset.filter(needs_human_intervention=True)
            elif needs_intervention_filter.lower() == 'false':
                queryset = queryset.filter(needs_human_intervention=False)
        
        if self.action == 'retrieve':
            # If ContactDetailSerializer uses a source like 'get_recent_messages_for_serializer'
            # which fetches messages, prefetching can be beneficial here.
            # Example for your 'recent_messages' in ContactDetailSerializer
            queryset = queryset.prefetch_related(
                Prefetch('messages', queryset=Message.objects.order_by('-timestamp')[:5])
            )
        return queryset


    @action(detail=True, methods=['get'], url_path='messages', permission_classes=[permissions.IsAuthenticated])
    def list_messages_for_contact(self, request, pk=None):
        contact = get_object_or_404(Contact, pk=pk)
        messages_queryset = Message.objects.filter(contact=contact).select_related('contact').order_by('-timestamp')
        
        page = self.paginate_queryset(messages_queryset)
        if page is not None:
            serializer = MessageListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = MessageListSerializer(messages_queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='toggle-block', permission_classes=[permissions.IsAuthenticated, IsAdminOrReadOnly])
    def toggle_block_status(self, request, pk=None):
        contact = get_object_or_404(Contact, pk=pk)
        contact.is_blocked = not contact.is_blocked
        contact.save(update_fields=['is_blocked', 'last_seen']) # last_seen is auto_now
        serializer = self.get_serializer(contact)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet
):
    queryset = Message.objects.all().select_related('contact').order_by('-timestamp')
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly] # Adjust IsAdminOrReadOnly if non-staff should create messages

    def get_serializer_class(self):
        if self.action == 'list':
            return MessageListSerializer
        return MessageSerializer

    def perform_create(self, serializer):
        """
        Handles the creation of an outgoing message and dispatches it for sending via Celery.
        """
        # The serializer expects 'contact' (PK), 'message_type', and 'content_payload'.
        # 'direction' and 'status' are set here for outgoing messages.
        # The request.user (agent sending the message) can also be logged if needed.
        # message_by_user = self.request.user # If you want to track which CRM user sent it

        message = serializer.save(
            direction='out',
            status='pending_dispatch', # Initial status before task picks it up
            timestamp=timezone.now() # Set send timestamp
            # created_by=message_by_user # Example if you add a 'created_by' FK to User
        )
        
        logger.info(
            f"Message record {message.id} created for contact {message.contact.whatsapp_id} "
            f"by user {self.request.user}. Type: {message.message_type}. Status: {message.status}."
        )

        try:
            # Fetch the active MetaAppConfig to get credentials for sending
            # This assumes MetaAppConfig has a manager method get_active_config()
            active_config = MetaAppConfig.objects.get_active_config()
            
            if active_config:
                logger.info(f"Dispatching Celery task send_whatsapp_message_task for Message ID: {message.id} using Config ID: {active_config.id}")
                send_whatsapp_message_task.delay(message.id, active_config.id)
                # The message status will be updated by the Celery task (e.g., to 'sent' or 'failed')
            else:
                logger.error(f"No active MetaAppConfig found. Message {message.id} for contact {message.contact.whatsapp_id} cannot be dispatched.")
                message.status = 'failed'
                message.error_details = {'error': 'No active MetaAppConfig was found for sending this message.'}
                message.status_timestamp = timezone.now()
                message.save(update_fields=['status', 'error_details', 'status_timestamp'])
        
        except MetaAppConfig.DoesNotExist:
            logger.critical(f"CRITICAL: No MetaAppConfig marked as active. Message {message.id} cannot be dispatched.")
            message.status = 'failed'; message.error_details = {'error': 'No active MetaAppConfig available.'}
            message.status_timestamp = timezone.now()
            message.save(update_fields=['status', 'error_details', 'status_timestamp'])
        except MetaAppConfig.MultipleObjectsReturned:
            logger.critical(f"CRITICAL: Multiple active MetaAppConfigs found. Message {message.id} cannot be dispatched reliably.")
            message.status = 'failed'; message.error_details = {'error': 'Multiple active MetaAppConfigs found.'}
            message.status_timestamp = timezone.now()
            message.save(update_fields=['status', 'error_details', 'status_timestamp'])
        except Exception as e:
            logger.error(f"Error dispatching Celery task for Message ID {message.id}: {e}", exc_info=True)
            message.status = 'failed'
            message.error_details = {'error': f'Failed to dispatch send task: {str(e)}'}
            message.status_timestamp = timezone.now()
            message.save(update_fields=['status', 'error_details', 'status_timestamp'])


    def get_queryset(self):
        queryset = super().get_queryset()
        contact_id = self.request.query_params.get('contact_id')
        if contact_id:
            try:
                queryset = queryset.filter(contact_id=int(contact_id))
            except ValueError:
                logger.warning(f"Invalid contact_id query parameter: {contact_id}")
                return Message.objects.none() # Return empty for invalid ID
        
        search_term = self.request.query_params.get('search')
        if search_term:
            queryset = queryset.filter(
                Q(text_content__icontains=search_term) |
                Q(contact__name__icontains=search_term) |
                Q(contact__whatsapp_id__icontains=search_term)
            )
        return queryset