# Task imports have been moved to apps.py ready() method to avoid
# AppRegistryNotReady errors. The ready() method ensures tasks are imported
# only after Django apps are fully loaded, preventing circular import issues
# that occur when models are imported during module initialization.
# 
# Celery will still discover these tasks through autodiscovery and the
# ready() method in apps.py, making them available in Django admin's
# periodic task dropdown.
