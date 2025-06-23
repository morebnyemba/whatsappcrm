# flows/views.py
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError # For model's full_clean

from .models import Flow, FlowStep, FlowTransition
from .serializers import FlowSerializer, FlowStepSerializer, FlowTransitionSerializer

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