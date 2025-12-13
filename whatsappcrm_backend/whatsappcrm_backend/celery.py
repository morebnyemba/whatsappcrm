import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsappcrm_backend.settings')

# Create the Celery application instance
app = Celery('whatsappcrm_backend')

# Configure Celery using settings from Django settings.py
# The 'CELERY_' namespace means all celery settings in settings.py should start with CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Configure task routing for separate workers
# This ensures tasks are dispatched to the correct queue for the appropriate worker
app.conf.task_routes = {
    # Football data tasks go to the football_data queue
    'football_data_app.*': {'queue': 'football_data'},
    
    # WhatsApp and general business tasks go to the celery queue for fast processing
    'meta_integration.tasks.*': {'queue': 'celery'},
    'conversations.tasks.*': {'queue': 'celery'},
    'flows.tasks.*': {'queue': 'celery'},
    'customer_data.tasks.*': {'queue': 'celery'},
    'paynow_integration.tasks.*': {'queue': 'celery'},
    'referrals.tasks.*': {'queue': 'celery'},
    'media_manager.tasks.*': {'queue': 'celery'},
}

# Default queue for any tasks not explicitly routed
app.conf.task_default_queue = 'celery'
app.conf.task_default_exchange = 'celery'
app.conf.task_default_routing_key = 'celery'

# Load task modules from all registered Django apps
app.autodiscover_tasks()

# Test task with result storage
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
    return {
        'status': 'success',
        'message': 'Celery is working with django-celery-results!'
    }
    
