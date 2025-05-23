# flows/urls.py
from django.urls import path, include
from rest_framework_nested import routers # Import from drf-nested-routers
from . import views

app_name = 'flows_api'
# Top-level router for Flows
router = routers.DefaultRouter()
router.register(r'flows', views.FlowViewSet, basename='flow')

# Nested router for FlowSteps under a Flow
# Generates URLs like: /api/v1/automation/flows/{flow_pk}/steps/
flows_steps_router = routers.NestedDefaultRouter(router, r'flows', lookup='flow')
flows_steps_router.register(r'steps', views.FlowStepViewSet, basename='flow-step')

# Nested router for FlowTransitions under a FlowStep
# Generates URLs like: /api/v1/automation/flows/{flow_pk}/steps/{step_pk}/transitions/
steps_transitions_router = routers.NestedDefaultRouter(flows_steps_router, r'steps', lookup='step')
steps_transitions_router.register(r'transitions', views.FlowTransitionViewSet, basename='flow-step-transition')

urlpatterns = [
    path('', include(router.urls)),
    path('', include(flows_steps_router.urls)),
    path('', include(steps_transitions_router.urls)),
]