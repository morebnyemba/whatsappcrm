# whatsappcrm_backend/flows/apps.py

from django.apps import AppConfig

class FlowsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'flows'
    verbose_name = "Conversational Flows Management"

    def ready(self):
        # Import signals if any
        pass
