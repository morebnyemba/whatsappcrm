import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsappcrm_backend.settings')

# Create the Celery application instance
app = Celery('whatsappcrm_backend')

# Configure Celery using settings from Django settings.py
# The 'CELERY_' namespace means all celery settings in settings.py should start with CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Simplified task routing - rely on explicit queue parameters in task definitions
# This prevents routing conflicts and ensures faster task dispatch
app.conf.task_routes = {
    # Football data tasks go to the football_data queue
    'football_data_app.tasks.*': {'queue': 'football_data'},
}

# Default queue for any tasks not explicitly routed (WhatsApp, flows, etc.)
app.conf.task_default_queue = 'celery'
app.conf.task_default_exchange = 'celery'
app.conf.task_default_routing_key = 'celery'

# Performance optimizations for faster task processing
app.conf.task_acks_late = True  # Acknowledge task after completion
app.conf.worker_prefetch_multiplier = 1  # Process one task at a time for fairness
app.conf.task_compression = 'gzip'  # Compress large task payloads

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
    
