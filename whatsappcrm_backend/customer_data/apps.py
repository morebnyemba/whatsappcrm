# whatsappcrm_backend/customer_data/apps.py

from django.apps import AppConfig

class CustomerDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'customer_data'
    verbose_name = "Customer Data & Profiles"
