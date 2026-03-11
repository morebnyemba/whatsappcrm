# flows/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError # For model's full_clean
from . import serializers
from .models import Flow, FlowStep, FlowTransition, WhatsAppFlow, WhatsAppFlowResponse
from .serializers import (
    FlowSerializer, FlowStepSerializer, FlowTransitionSerializer,
    WhatsAppFlowSerializer, WhatsAppFlowResponseSerializer,
)

import logging


logger = logging.getLogger(__name__)

class FlowViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing Flows (Create, Read, Update, Delete).
    Allows full CRUD operations for Flow objects.
    """
    queryset = Flow.objects.all().prefetch_related('steps').order_by('-updated_at', 'name')
    serializer_class = FlowSerializer
    # TODO: Replace with more granular permissions for production
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        """
        Called by ModelViewSet's create() method.
        Ensures model validation (full_clean) is run via model's save() method.
        """
        try:
            with transaction.atomic():
                # The Flow model's save() method now calls self.full_clean()
                serializer.save()
                logger.info(f"Flow '{serializer.instance.name}' created successfully.")
        except DjangoValidationError as e:
            logger.error(f"Model validation failed during Flow creation: {e.message_dict if hasattr(e, 'message_dict') else list(e)}")
            # DRF's exception handler will convert this to a 400 response
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))
        except Exception as e:
            logger.error(f"Unexpected error during Flow creation: {e}", exc_info=True)
            raise # Re-raise other unexpected errors for DRF's default handler

    def perform_update(self, serializer):
        """
        Called by ModelViewSet's update()/partial_update() methods.
        Ensures model validation (full_clean) is run.
        """
        try:
            with transaction.atomic():
                # The Flow model's save() method now calls self.full_clean()
                serializer.save()
                logger.info(f"Flow '{serializer.instance.name}' (PK: {serializer.instance.pk}) updated successfully.")
        except DjangoValidationError as e:
            logger.error(f"Model validation failed during Flow update (PK: {serializer.instance.pk}): {e.message_dict if hasattr(e, 'message_dict') else list(e)}")
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))
        except Exception as e:
            logger.error(f"Unexpected error during Flow update (PK: {serializer.instance.pk}): {e}", exc_info=True)
            raise


class FlowStepViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing FlowSteps.
    Supports filtering by 'flow_id' query parameter (e.g., ?flow_id=<id>)
    and automatic filtering if used with nested routers (e.g., /flows/{flow_pk}/steps/).
    """
    queryset = FlowStep.objects.select_related('flow').all().order_by('flow__name', 'created_at') # Default ordering from model Meta is also good
    serializer_class = FlowStepSerializer
    # TODO: Replace with more granular permissions
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Filters queryset based on 'flow_pk' from URL kwargs (if using nested routers)
        or 'flow_id' from query parameters.
        """
        queryset = super().get_queryset()
        flow_pk = self.kwargs.get('flow_pk') # From URL if nested: /flows/{flow_pk}/steps/

        if flow_pk:
            queryset = queryset.filter(flow_id=flow_pk)
        else:
            # Fallback for direct access with query parameter
            flow_id_param = self.request.query_params.get('flow_id')
            if flow_id_param:
                try:
                    queryset = queryset.filter(flow_id=int(flow_id_param))
                except ValueError:
                    logger.warning(f"Invalid flow_id query parameter for FlowSteps: {flow_id_param}")
                    return FlowStep.objects.none() # Return empty for invalid ID
        return queryset

    def perform_create(self, serializer):
        """
        Automatically associate with parent Flow if using nested URL,
        and ensure model validation is run.
        """
        flow_pk = self.kwargs.get('flow_pk')
        flow_instance = None

        if flow_pk:
            try:
                flow_instance = Flow.objects.get(pk=flow_pk)
            except Flow.DoesNotExist:
                raise serializers.ValidationError({"flow": f"Parent Flow with pk={flow_pk} not found."})
        
        # If flow is also in serializer.validated_data (e.g., from a non-nested request),
        # DRF has already validated it if it's a PrimaryKeyRelatedField.
        # If flow_instance is set from URL, we pass it to save to ensure association.
        save_kwargs = {}
        if flow_instance:
            save_kwargs['flow'] = flow_instance

        try:
            with transaction.atomic():
                # The FlowStep model's save() method calls self.full_clean()
                serializer.save(**save_kwargs)
                logger.info(f"FlowStep '{serializer.instance.name}' created successfully for Flow PK {serializer.instance.flow_id}.")
        except DjangoValidationError as e:
            logger.error(f"Model validation failed during FlowStep creation: {e.message_dict if hasattr(e, 'message_dict') else list(e)}")
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))
        except Exception as e:
            logger.error(f"Unexpected error during FlowStep creation: {e}", exc_info=True)
            raise

    def perform_update(self, serializer):
        """
        Ensure model validation (full_clean) is run on update.
        """
        try:
            with transaction.atomic():
                # The FlowStep model's save() method calls self.full_clean()
                serializer.save()
                logger.info(f"FlowStep '{serializer.instance.name}' (PK: {serializer.instance.pk}) updated successfully.")
        except DjangoValidationError as e:
            logger.error(f"Model validation failed during FlowStep update (PK: {serializer.instance.pk}): {e.message_dict if hasattr(e, 'message_dict') else list(e)}")
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))
        except Exception as e:
            logger.error(f"Unexpected error during FlowStep update (PK: {serializer.instance.pk}): {e}", exc_info=True)
            raise


class FlowTransitionViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing FlowTransitions.
    Supports filtering by parent IDs if using nested routers or query parameters.
    """
    queryset = FlowTransition.objects.select_related('current_step__flow', 'next_step__flow').all() # Default order from model Meta
    serializer_class = FlowTransitionSerializer
    # TODO: Replace with more granular permissions
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        flow_pk = self.kwargs.get('flow_pk') # From /flows/{flow_pk}/...
        step_pk = self.kwargs.get('step_pk') # From /flows/{flow_pk}/steps/{step_pk}/transitions/

        if step_pk: # Transitions for a specific current_step
            queryset = queryset.filter(current_step_id=step_pk)
            if flow_pk: # Additional check for consistency if flow_pk is also in URL
                queryset = queryset.filter(current_step__flow_id=flow_pk)
        elif flow_pk: # All transitions within a given flow
            queryset = queryset.filter(current_step__flow_id=flow_pk)
        else:
            # Fallback for direct access with query parameters
            current_step_id_param = self.request.query_params.get('current_step_id')
            if current_step_id_param:
                try:
                    queryset = queryset.filter(current_step_id=int(current_step_id_param))
                except ValueError:
                    return FlowTransition.objects.none()
        return queryset

    def perform_create(self, serializer):
        # If nested under a step, current_step can be auto-assigned from URL
        current_step_pk_from_url = self.kwargs.get('step_pk')
        current_step_from_data = serializer.validated_data.get('current_step')
        
        save_kwargs = {}
        if current_step_pk_from_url and (not current_step_from_data or current_step_from_data.pk != int(current_step_pk_from_url)):
            try:
                # Ensure current_step from URL is used if provided and different or not in data
                save_kwargs['current_step'] = FlowStep.objects.get(pk=current_step_pk_from_url)
                # The serializer's validate method will check if next_step belongs to the same flow
            except FlowStep.DoesNotExist:
                raise serializers.ValidationError({"current_step": f"Parent FlowStep with pk={current_step_pk_from_url} not found."})
        
        try:
            with transaction.atomic():
                # The FlowTransition model's save() method calls self.full_clean()
                serializer.save(**save_kwargs)
                logger.info(f"FlowTransition (PK: {serializer.instance.pk}) created successfully.")
        except DjangoValidationError as e: # From model's full_clean()
            logger.error(f"Model validation failed during FlowTransition creation: {e.message_dict if hasattr(e, 'message_dict') else list(e)}")
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))
        except Exception as e:
            logger.error(f"Unexpected error during FlowTransition creation: {e}", exc_info=True)
            raise

    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                # The FlowTransition model's save() method calls self.full_clean()
                serializer.save()
                logger.info(f"FlowTransition (PK: {serializer.instance.pk}) updated successfully.")
        except DjangoValidationError as e:
            logger.error(f"Model validation failed during FlowTransition update (PK: {serializer.instance.pk}): {e.message_dict if hasattr(e, 'message_dict') else list(e)}")
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))
        except Exception as e:
            logger.error(f"Unexpected error during FlowTransition update (PK: {serializer.instance.pk}): {e}", exc_info=True)
            raise


class WhatsAppFlowViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing WhatsApp interactive flows.
    Supports CRUD plus custom actions for syncing and publishing flows with Meta.

    Create endpoint accepts an optional ``auto_sync`` boolean field.  When true
    (and ``flow_json`` + ``meta_app_config`` are provided), the flow is
    automatically created on Meta's platform, its JSON is uploaded, and the
    data-exchange ``endpoint_uri`` is configured — all in a single request.
    """
    queryset = WhatsAppFlow.objects.select_related('meta_app_config', 'flow_definition').all()
    serializer_class = WhatsAppFlowSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
                logger.info(f"WhatsAppFlow '{serializer.instance.name}' created successfully.")
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))

    def create(self, request, *args, **kwargs):
        """
        Create a WhatsApp flow.  Pass ``"auto_sync": true`` (boolean) in the
        request body to immediately sync the flow to Meta's platform after
        creation (create → upload JSON → set endpoint_uri).
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Extract auto_sync before saving so it is not forwarded to the model
        auto_sync = bool(serializer.validated_data.pop('auto_sync', False))
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        response = Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

        if auto_sync:
            pk = serializer.instance.pk
            try:
                whatsapp_flow = WhatsAppFlow.objects.get(pk=pk)
                if whatsapp_flow.meta_app_config and whatsapp_flow.flow_json:
                    from .whatsapp_flow_service import WhatsAppFlowService
                    service = WhatsAppFlowService(whatsapp_flow.meta_app_config)
                    success = service.sync_flow(whatsapp_flow)
                    whatsapp_flow.refresh_from_db()
                    if success:
                        logger.info(
                            f"Auto-synced WhatsAppFlow '{whatsapp_flow.name}' "
                            f"(flow_id: {whatsapp_flow.flow_id}) after creation."
                        )
                    else:
                        logger.warning(
                            f"Auto-sync failed for WhatsAppFlow '{whatsapp_flow.name}': "
                            f"{whatsapp_flow.sync_error}"
                        )
                    # Return the updated serializer data (includes flow_id, sync_status)
                    response.data.update(WhatsAppFlowSerializer(whatsapp_flow).data)
                else:
                    logger.info(
                        f"auto_sync requested but WhatsAppFlow '{whatsapp_flow.name}' "
                        f"is missing meta_app_config or flow_json; skipping auto-sync."
                    )
            except Exception as e:
                logger.error(f"Error during auto-sync after WhatsApp flow creation: {e}", exc_info=True)
                # Don't fail the create — the record was saved successfully

        return response

    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
                logger.info(f"WhatsAppFlow '{serializer.instance.name}' (PK: {serializer.instance.pk}) updated successfully.")
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else list(e))

    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """Sync this flow with Meta's platform (create + upload JSON)."""
        whatsapp_flow = self.get_object()
        from .whatsapp_flow_service import WhatsAppFlowService

        try:
            service = WhatsAppFlowService(whatsapp_flow.meta_app_config)
            success = service.sync_flow(whatsapp_flow)
            whatsapp_flow.refresh_from_db()

            if success:
                return Response(
                    WhatsAppFlowSerializer(whatsapp_flow).data,
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"detail": whatsapp_flow.sync_error or "Sync failed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as e:
            logger.error(f"Error syncing WhatsApp flow {pk}: {e}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish this flow on Meta's platform."""
        whatsapp_flow = self.get_object()
        from .whatsapp_flow_service import WhatsAppFlowService

        if not whatsapp_flow.flow_id:
            return Response(
                {"detail": "Flow must be synced before publishing. Call sync first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = WhatsAppFlowService(whatsapp_flow.meta_app_config)
            success = service.publish_flow(whatsapp_flow)
            whatsapp_flow.refresh_from_db()

            if success:
                return Response(
                    WhatsAppFlowSerializer(whatsapp_flow).data,
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"detail": whatsapp_flow.sync_error or "Publish failed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as e:
            logger.error(f"Error publishing WhatsApp flow {pk}: {e}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['post'])
    def import_from_meta(self, request):
        """
        Import WhatsApp UI Flow definitions from Meta's platform into the
        local database. Fetches all flows for the specified (or default)
        MetaAppConfig, downloads their JSON assets, and creates or updates
        local WhatsAppFlow records.

        Optional body parameter:
            meta_app_config_id: ID of the MetaAppConfig to use (defaults to
                                the first active config).
        """
        from meta_integration.models import MetaAppConfig
        from .whatsapp_flow_service import WhatsAppFlowService

        config_id = request.data.get('meta_app_config_id')
        try:
            if config_id:
                meta_config = MetaAppConfig.objects.get(pk=config_id)
            else:
                meta_config = MetaAppConfig.objects.get_active_config()
        except MetaAppConfig.DoesNotExist:
            if config_id:
                msg = f"MetaAppConfig with ID {config_id} not found."
            else:
                msg = "No active MetaAppConfig found. Provide a valid meta_app_config_id."
            return Response(
                {"detail": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            service = WhatsAppFlowService(meta_config)
            results = service.import_flows_from_meta()
            return Response(
                {
                    "detail": (
                        f"Import complete: {results['imported']} imported, "
                        f"{results['updated']} updated, {results['errors']} errors."
                    ),
                    "results": results,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error importing flows from Meta: {e}", exc_info=True)
            return Response(
                {"detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class WhatsAppFlowResponseViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API endpoint for viewing WhatsApp flow responses.
    Supports filtering by whatsapp_flow_id and is_processed.
    """
    queryset = WhatsAppFlowResponse.objects.select_related('whatsapp_flow', 'contact').all()
    serializer_class = WhatsAppFlowResponseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        flow_id = self.request.query_params.get('whatsapp_flow_id')
        if flow_id:
            queryset = queryset.filter(whatsapp_flow_id=flow_id)
        is_processed = self.request.query_params.get('is_processed')
        if is_processed is not None:
            queryset = queryset.filter(is_processed=is_processed.lower() == 'true')
        return queryset