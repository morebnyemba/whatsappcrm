from django.apps import AppConfig


class FootballDataAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'football_data_app'
    verbose_name = 'Football Data & Betting'
    
    def ready(self):
        """
        Import tasks when the app is ready to ensure they are registered with Celery.
        This is crucial for tasks to appear in Django admin's periodic task dropdown.
        """
        try:
            # Import tasks to ensure they're registered with Celery
            from . import tasks  # noqa: F401
            from . import tasks_apifootball  # noqa: F401
            from . import tasks_api_football_v3  # noqa: F401
        except ImportError:
            pass
