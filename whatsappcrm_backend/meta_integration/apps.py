# whatsappcrm_backend/meta_integration/apps.py

from django.apps import AppConfig

class MetaIntegrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'meta_integration'
    verbose_name = "Meta Integration"

    def ready(self):
        # You can import signals or other setup code here if needed
        pass
