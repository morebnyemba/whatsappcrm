import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsappcrm_backend.settings')

# Create the Celery application instance
app = Celery('whatsappcrm_backend')

# Configure Celery using settings from Django settings.py
# The 'CELERY_' namespace means all celery settings in settings.py should start with CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Fix for AttributeError: 'str' object has no attribute '__module__'
# This ensures the worker pool class is properly set when using solo pool
# The error occurs when pool_cls is a string instead of a class reference
try:
    from celery.concurrency.solo import TaskPool as SoloPool
    app.conf.worker_pool = SoloPool
except ImportError:
    # Fallback to string notation if import fails
    app.conf.worker_pool = 'solo'

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
