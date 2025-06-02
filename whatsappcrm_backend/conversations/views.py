# whatsappcrm_backend/conversations/views.py

from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Prefetch
from django.utils import timezone
from django.shortcuts import get_object_or_404
import logging 

from .models import Contact, Message 
from .serializers import (
    ContactSerializer,
    MessageSerializer,
    MessageListSerializer,
    ContactDetailSerializer,
)
from meta_integration.tasks import send_whatsapp_message_task
from meta_integration.models import MetaAppConfig 

logger = logging.getLogger(__name__) 

class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS: 
            return True
        return request.user and request.user.is_staff


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all().order_by('-last_seen')
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ContactDetailSerializer
        return ContactSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search_term = self.request.query_params.get('search', None)
        if search_term:
            queryset = queryset.filter(
                Q(name__icontains=search_term) | 
                Q(whatsapp_id__icontains=search_term)
            )
        
        needs_intervention_filter = self.request.query_params.get('needs_human_intervention', None)
        if needs_intervention_filter is not None:
            if needs_intervention_filter.lower() == 'true':
                queryset = queryset.filter(needs_human_intervention=True)
            elif needs_intervention_filter.lower() == 'false':
                queryset = queryset.filter(needs_human_intervention=False)
        
        if self.action == 'retrieve':
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
        contact.save(update_fields=['is_blocked', 'last_seen']) 
        serializer = self.get_serializer(contact)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet
):
    queryset = Message.objects.all().select_related('contact').order_by('-timestamp')
    permission_classes = [permissions.IsAuthenticated] 

    def get_serializer_class(self):
        if self.action == 'list':
            return MessageListSerializer
        return MessageSerializer

    def perform_create(self, serializer):
        message = serializer.save(
            direction='out',
            status='pending_dispatch', 
            timestamp=timezone.now(),
        )
        
        logger.info(
            f"Message record {message.id} created for contact {message.contact.whatsapp_id} "
            f"by user {self.request.user}. Type: {message.message_type}. Status: {message.status}."
        )

        contact_to_update = message.contact
        if contact_to_update.needs_human_intervention:
            contact_to_update.needs_human_intervention = False
            contact_to_update.intervention_resolved_at = timezone.now()
            contact_to_update.save(update_fields=['needs_human_intervention', 'intervention_resolved_at', 'last_seen'])
            logger.info(f"Cleared human intervention flag for contact {contact_to_update.whatsapp_id} by user {self.request.user}.")

        try:
            active_config = MetaAppConfig.objects.get_active_config()
            
            if active_config:
                logger.info(f"Dispatching Celery task send_whatsapp_message_task for Message ID: {message.id} using Config ID: {active_config.id}")
                send_whatsapp_message_task.delay(message.id, active_config.id)
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
                return Message.objects.none() 
        
        search_term = self.request.query_params.get('search')
        if search_term:
            queryset = queryset.filter(
                Q(content__icontains=search_term) | 
                Q(contact__name__icontains=search_term) |
                Q(contact__whatsapp_id__icontains=search_term)
            )
        return queryset