import os
from celery import Celery
from celery.signals import worker_init

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsappcrm_backend.settings')

# Create the Celery application instance
app = Celery('whatsappcrm_backend')

# Configure Celery using settings from Django settings.py
# The 'CELERY_' namespace means all celery settings in settings.py should start with CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps
app.autodiscover_tasks()

# Fix for AttributeError: 'str' object has no attribute '__module__'
# This ensures the worker pool class is properly set when using solo pool
# The error occurs when pool_cls is a string instead of a class reference
# We need to convert the string setting to an actual class
# This is deferred to worker initialization to avoid circular import issues
@worker_init.connect
def setup_worker_pool(**kwargs):
    """
    Convert worker_pool string to actual class reference when worker initializes.
    This is deferred to avoid circular import issues during Django startup.
    """
    try:
        worker_pool = getattr(app.conf, 'worker_pool', None)
        if worker_pool and isinstance(worker_pool, str):
            from kombu.utils.imports import symbol_by_name
            # Map common pool names to their full paths
            pool_map = {
                'solo': 'celery.concurrency.solo:TaskPool',
                'prefork': 'celery.concurrency.prefork:TaskPool',
                'threads': 'celery.concurrency.threads:TaskPool',
                'eventlet': 'celery.concurrency.eventlet:TaskPool',
                'gevent': 'celery.concurrency.gevent:TaskPool',
            }
            pool_path = pool_map.get(worker_pool, worker_pool)
            app.conf.worker_pool = symbol_by_name(pool_path)
    except (ImportError, AttributeError, KeyError) as e:
        # If conversion fails, log warning but leave as string (Celery will handle it)
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to convert worker_pool '{worker_pool}' to class: {e}")

# Test task with result storage
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
    return {
        'status': 'success',
        'message': 'Celery is working with django-celery-results!'
    }
