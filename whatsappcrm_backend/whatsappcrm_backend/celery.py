# IMPORTANT: gevent monkey-patching must happen before anything else.
# This makes standard libraries (like sockets, requests) cooperative.
import os
import sys

# Only apply gevent monkey-patching if the process is a Celery worker.
# This prevents import-time side effects when running other management commands
# like 'migrate' or 'shell', which was causing a RuntimeError.
if 'celery' in ' '.join(sys.argv):
    import gevent.monkey
    gevent.monkey.patch_all()

from celery import Celery
import django

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsappcrm_backend.settings')

# This is crucial for Celery to be able to use Django models.
django.setup()

# Create the Celery application instance
app = Celery('whatsappcrm_backend')

# Configure Celery using settings from Django settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
# Celery will look for a tasks.py file in each installed app.
app.autodiscover_tasks()

# Optional: A debug task to verify setup
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
    return {
        'status': 'success',
        'message': 'Celery is working with gevent and django-celery-results!'
    }
    
