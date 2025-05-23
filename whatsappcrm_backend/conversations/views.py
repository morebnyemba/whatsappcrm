# whatsappcrm_backend/conversations/views.py

from rest_framework import viewsets, permissions, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Prefetch
from django.utils import timezone
from django.shortcuts import get_object_or_404


from .models import Contact, Message
from .serializers import (
    ContactSerializer,
    MessageSerializer,
    MessageListSerializer,
    ContactDetailSerializer,
)

# It's good practice to have a shared permissions file if IsAdminOrReadOnly is used in multiple apps
# For now, defining it here for simplicity if not already in a central place.
# from ..core.permissions import IsAdminOrReadOnly # Example if you create a core app with permissions

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
    # Default permission: only authenticated users can access, admins can modify.
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            # For the detail view of a contact, use a serializer that might include more details like recent messages.
            return ContactDetailSerializer
        return ContactSerializer

    def get_queryset(self):
        """
        Prefetch recent messages for the detail view to optimize queries
        if ContactDetailSerializer is used and sources 'messages_preview' from the model.
        """
        queryset = super().get_queryset()
        if self.action == 'retrieve':
            # Example: If Contact model has a 'messages_preview' property that queries messages,
            # prefetching 'messages' can help if that property uses it.
            # This depends on how 'messages_preview' is implemented in the model.
            # A more direct prefetch for ContactDetailSerializer if it uses a related name:
            # queryset = queryset.prefetch_related(
            #     Prefetch('messages', queryset=Message.objects.order_by('-timestamp')[:10], to_attr='recent_messages_data')
            # )
            # Then the serializer would source from 'recent_messages_data'.
            # For the current serializer sourcing 'messages_preview', ensure the model property is efficient.
            pass # No specific prefetch here unless model's messages_preview is optimized with it
        return queryset


    @action(detail=True, methods=['get'], url_path='messages', permission_classes=[permissions.IsAuthenticated])
    def list_messages_for_contact(self, request, pk=None):
        """
        Retrieves all messages for a specific contact, ordered by timestamp.
        """
        contact = get_object_or_404(Contact, pk=pk)
        
        # Apply pagination to the messages queryset
        messages_queryset = Message.objects.filter(contact=contact).select_related('contact').order_by('-timestamp')
        
        page = self.paginate_queryset(messages_queryset)
        if page is not None:
            serializer = MessageListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = MessageListSerializer(messages_queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='toggle-block', permission_classes=[permissions.IsAuthenticated, IsAdminOrReadOnly])
    def toggle_block_status(self, request, pk=None):
        """
        Toggles the 'is_blocked' status of a contact. Only for admin users.
        """
        contact = get_object_or_404(Contact, pk=pk)
        contact.is_blocked = not contact.is_blocked
        contact.save(update_fields=['is_blocked']) # Optimize by updating only the changed field
        serializer = self.get_serializer(contact) # Return the updated contact
        return Response(serializer.data, status=status.HTTP_200_OK)


class MessageViewSet(
    mixins.ListModelMixin,      # GET /messages/ (list)
    mixins.RetrieveModelMixin,  # GET /messages/{id}/ (detail)
    mixins.CreateModelMixin,    # POST /messages/ (create new outgoing message)
    # UpdateModelMixin is intentionally omitted as messages are generally immutable post-creation,
    # except for their status, which should be updated by the system (e.g., Meta webhook handler).
    # DestroyModelMixin is also omitted; message deletion might be a special admin/system task.
    viewsets.GenericViewSet
):
    """
    API endpoint for Messages.
    - Allows listing and retrieving messages for conversation history.
    - Allows creating new (outgoing) messages.
    Permissions can be set for agents to create messages.
    """
    queryset = Message.objects.all().select_related('contact').order_by('-timestamp')
    # Default permission: Authenticated users can access, admins can modify (create in this case).
    # You might want a custom permission like 'IsAgentOrAdmin' for creating messages.
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly] 

    def get_serializer_class(self):
        if self.action == 'list':
            return MessageListSerializer
        return MessageSerializer # For retrieve and create

    def perform_create(self, serializer):
        """
        Handles the creation of an outgoing message.
        The actual sending logic (calling Meta API) should be triggered here,
        ideally asynchronously (e.g., via a Celery task).
        """
        # The serializer's 'contact' field is write_only=True, expecting a contact ID.
        # 'direction' should be 'out' for messages created via this API.
        # 'status' should be initialized (e.g., 'pending_send' or 'queued').
        
        # Ensure the user making the request (agent) is associated if needed, or log actor.
        # actor = self.request.user 

        message = serializer.save(direction='out', status='pending_send')
        
        # TODO: Implement robust message sending logic.
        # This is a critical part and should involve:
        # 1. Getting the active MetaAppConfig.
        # 2. Constructing the correct payload for Meta based on message.message_type and message.content_payload.
        # 3. Calling meta_integration.utils.send_whatsapp_message.
        # 4. Updating the message record with wamid, status ('sent' or 'failed'), error_details from Meta's response.
        # 5. THIS SHOULD BE DONE ASYNCHRONOUSLY (e.g., using Celery) to avoid long request times.

        # Example placeholder for asynchronous task trigger:
        # from ..tasks import send_whatsapp_message_task # Assuming you create a tasks.py
        # send_whatsapp_message_task.delay(message.id)

        logger.info(f"Outgoing message {message.id} for contact {message.contact.whatsapp_id} created by {self.request.user}. Status: {message.status}. Awaiting asynchronous send.")
        # The response will be the serialized message as it's stored before sending attempt.
        # The frontend might need to poll for status updates or use WebSockets if real-time status is critical.

    def get_queryset(self):
        """
        Overrides the default queryset to allow filtering.
        Example filters: by contact_id, or a general search term.
        """
        queryset = super().get_queryset()
        
        contact_id = self.request.query_params.get('contact_id')
        if contact_id:
            queryset = queryset.filter(contact_id=contact_id)
        
        search_term = self.request.query_params.get('search')
        if search_term:
            # Example search: across text_content, contact name, or contact WhatsApp ID.
            queryset = queryset.filter(
                Q(text_content__icontains=search_term) |
                Q(contact__name__icontains=search_term) |
                Q(contact__whatsapp_id__icontains=search_term)
            )
            # Note: Searching within JSONField (content_payload) can be database-specific and less performant.
            # Consider extracting more common fields if they need to be searched frequently.

        return queryset
