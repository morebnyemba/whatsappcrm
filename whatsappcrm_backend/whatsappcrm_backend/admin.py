# admin.py (in any of your apps)
from django_celery_results.models import TaskResult
from django.contrib import admin

admin.site.register(TaskResult)