# whatsappcrm_backend/conversations/apps.py

from django.apps import AppConfig

class ConversationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'conversations'
    verbose_name = "Conversations Management"

    def ready(self):
        # You can import signals here if needed in the future
        # For example: from . import signals
        pass
