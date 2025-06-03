import os
from celery import Celery
import django

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsappcrm_backend.settings')
django.setup()

# Create the Celery application instance
app = Celery('whatsappcrm_backend')

# Configure Celery using settings from Django settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

# ---- TEMPORARY DEBUG PRINT ----
print(f"[DEBUG celery.py] CELERY_BROKER_URL from app.conf: {app.conf.broker_url}")
print(f"[DEBUG celery.py] CELERY_RESULT_BACKEND from app.conf: {app.conf.result_backend}")
# ---- END TEMPORARY DEBUG PRINT ----

# This ensures all task results will be stored in django-db
app.conf.result_backend = 'django-db'
app.conf.result_extended = True  # Store additional task metadata

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
    
# whatsappcrm_backend/celery.py
app.conf.beat_schedule = {
    'update-football-fixtures-every-hour': {
        'task': 'football_data_app.update_football_fixtures', # Updated task name
        'schedule': 3600.0, 
    },
}