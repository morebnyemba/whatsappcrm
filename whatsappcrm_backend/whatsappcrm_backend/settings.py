# whatsappcrm_backend/whatsappcrm_backend/settings.py

import os
from pathlib import Path
from datetime import timedelta
import dotenv # For loading .env file

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent # This should point to whatsappcrm_backend directory

# --- Environment Variables ---
# Load .env file from the project root (one level up from BASE_DIR if Dockerfile is inside whatsappcrm_backend)
# For Docker, .env is usually handled by docker-compose at the compose file level.
# If running locally, ensure .env is in the directory where manage.py is.
dotenv_file = BASE_DIR / '.env'
if os.path.isfile(dotenv_file):
    dotenv.load_dotenv(dotenv_file)
else:
    # If .env is at repository root (one level up from BASE_DIR which is whatsappcrm_backend)
    repo_root_dotenv = BASE_DIR.parent / '.env'
    if os.path.isfile(repo_root_dotenv):
        dotenv.load_dotenv(repo_root_dotenv)


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-fallback-key-for-dev-only-replace-me-in-env')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS_STRING = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1') # Add your domains/IPs
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_STRING.split(',') if host.strip()]
if DEBUG and not ALLOWED_HOSTS: # Default for local dev if empty
    ALLOWED_HOSTS = ['localhost', '127.0.0.1']


CSRF_TRUSTED_ORIGINS_STRING = os.getenv('CSRF_TRUSTED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173') # Add your frontend origins
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in CSRF_TRUSTED_ORIGINS_STRING.split(',') if origin.strip()]


# Application definition
INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_celery_results',
    'django_celery_beat',

    'football_data_app.apps.FootballDataAppConfig',
    'media_manager.apps.MediaManagerConfig',
    "stats",
    'meta_integration.apps.MetaIntegrationConfig',
    'conversations.apps.ConversationsConfig',
    'flows.apps.FlowsConfig',
    'customer_data.apps.CustomerDataConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'whatsappcrm_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'whatsappcrm_backend.wsgi.application'
ASGI_APPLICATION = 'whatsappcrm_backend.asgi.application'


# Database
DB_ENGINE_DEFAULT = 'django.db.backends.postgresql'
DB_NAME_DEFAULT = 'whatsapp_crm_dev'
DB_USER_DEFAULT = 'crm_user'
DB_PASSWORD_DEFAULT = 'your_db_password' # IMPORTANT: Set in .env
DB_HOST_DEFAULT = 'db' # Service name from docker-compose
DB_PORT_DEFAULT = '5432'

DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', DB_ENGINE_DEFAULT),
        'NAME': os.getenv('DB_NAME', DB_NAME_DEFAULT),
        'USER': os.getenv('DB_USER', DB_USER_DEFAULT),
        'PASSWORD': os.getenv('DB_PASSWORD', DB_PASSWORD_DEFAULT),
        'HOST': os.getenv('DB_HOST', DB_HOST_DEFAULT),
        'PORT': os.getenv('DB_PORT', DB_PORT_DEFAULT),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Harare' # Important for Celery Beat schedules and database timestamps
USE_I18N = True
USE_TZ = True # Recommended for Django projects

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles' # Directory where collectstatic will gather them

# Media files (User-uploaded content)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'whatsapp_media_assets' # Your existing media directory

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.getenv('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', '60'))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.getenv('JWT_REFRESH_TOKEN_LIFETIME_DAYS', '7'))),
    'ROTATE_REFRESH_TOKENS': os.getenv('JWT_ROTATE_REFRESH_TOKENS', 'True') == 'True',
    'BLACKLIST_AFTER_ROTATION': os.getenv('JWT_BLACKLIST_AFTER_ROTATION', 'True') == 'True',
    'UPDATE_LAST_LOGIN': os.getenv('JWT_UPDATE_LAST_LOGIN', 'False') == 'True',
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id', 'USER_ID_CLAIM': 'user_id',
}

CORS_ALLOWED_ORIGINS_STRING = os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173')
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS_STRING.split(',') if origin.strip()]
CORS_ALLOW_CREDENTIALS = True

# --- Celery Configuration ---
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0') # 'redis' is service name in docker-compose
CELERY_RESULT_BACKEND = 'django-db' # Using django-celery-results
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE # Use Django's timezone
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.getenv('CELERY_TASK_TIME_LIMIT_SECONDS', '3600')) # 1 hour
CELERY_RESULT_EXTENDED = True

# Celery Worker Pool and Concurrency Settings
# Worker pool type is best set via CLI: -P <pool_name> (e.g., -P gevent)
# 'prefork' (multiprocessing) is default. 'gevent' or 'eventlet' for I/O-bound tasks.
CELERY_WORKER_POOL = os.getenv('CELERY_WORKER_POOL', 'gevent') # Default to gevent for I/O tasks
CELERY_WORKER_CONCURRENCY = int(os.getenv('CELERY_WORKER_CONCURRENCY', '100')) # Default for gevent/eventlet, adjust based on load and API limits. For prefork, set to CPU cores.

# Celery Beat (Scheduled Tasks)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
from celery.schedules import crontab

API_FOOTBALL_KEY = os.getenv('API_FOOTBALL_KEY', None) # Ensure this is in your .env
API_FOOTBALL_CALL_DELAY_SECONDS = float(os.getenv('API_FOOTBALL_CALL_DELAY_SECONDS', '2.0'))

CELERY_BEAT_SCHEDULE = {
    'update-major-leagues-football-data-daily': {
        'task': 'football_data.run_full_league_data_update_task',
        'schedule': crontab(hour=3, minute=0),  # Every day at 3:00 AM (server time)
        # Args: ([league_api_ids], season_year, fetch_odds_boolean)
        # IMPORTANT: Replace these with actual league IDs and current season for api-football.com
        'args': ([39, 140, 61, 78, 135], 2023, True), # Example: PL, La Liga, Ligue 1, Bundesliga, Serie A
        'options': {'expires': 60 * 60 * 4, 'queue': 'football_data_queue'},
    },
    'fetch-odds-for-upcoming-football-fixtures-hourly': {
        'task': 'football_data.fetch_odds_for_upcoming_fixtures_task',
        'schedule': crontab(minute=15),  # Every hour at 15 minutes past
        'args': (48, 150, 0.1), # Lookahead 48h, limit 150 fixtures, 0.1s stagger
        'options': {'expires': 60 * 45, 'queue': 'odds_fetch_queue'},
    },
}

CONVERSATION_EXPIRY_DAYS = int(os.getenv('CONVERSATION_EXPIRY_DAYS', '60'))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}', 'style': '{'},
        'simple': {'format': '[{asctime}] {levelname} {name} {module}.{funcName}:{lineno} {message}', 'style': '{', 'datefmt': '%Y-%m-%d %H:%M:%S'},
        'celery_standard': {'format': '[%(asctime)s: %(levelname)s/%(processName)s] [%(task_name)s(%(task_id)s)] %(message)s', 'datefmt': '%Y-%m-%d %H:%M:%S'}
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        'celery_console': {'class': 'logging.StreamHandler', 'formatter': 'celery_standard'}
    },
    'root': {'handlers': ['console'], 'level': os.getenv('DJANGO_ROOT_LOG_LEVEL', 'INFO')},
    'loggers': {
        'django': {'handlers': ['console'], 'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'), 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'celery': {'handlers': ['celery_console'], 'level': os.getenv('CELERY_LOG_LEVEL', 'INFO'), 'propagate': False},
        'celery.beat': {'handlers': ['celery_console'], 'level': os.getenv('CELERY_BEAT_LOG_LEVEL', 'INFO'), 'propagate': False},
        'football_data_app': {'handlers': ['console'], 'level': os.getenv('APP_FOOTBALL_DATA_LOG_LEVEL', 'DEBUG'), 'propagate': False},
        # ... other app loggers from your original settings ...
        'meta_integration': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
        'conversations': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
        'flows': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
        'customer_data': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
    },
}

WHATSAPP_APP_SECRET = os.getenv('WHATSAPP_APP_SECRET', None)

JAZZMIN_SETTINGS = {
    "site_title": "AutoWhasapp", "site_header": "AutoWhatsapp", "site_brand": "A-W",
    "site_logo_classes": "img-circle", "welcome_sign": "Welcome to the AutoWhatsapp Admin",
    "copyright": "Slyker Tech Web Services.",
    "search_model": ["auth.User", "meta_integration.MetaAppConfig", "conversations.Contact", "flows.Flow", "football_data_app.FootballFixture"],
    "user_avatar": None,
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"model": "auth.User"},
    ],
    "show_sidebar": True, "navigation_expanded": True, "hide_apps": [], "hide_models": [],
    "icons": {
        "auth": "fas fa-users-cog", "auth.user": "fas fa-user", "auth.Group": "fas fa-users",
        "meta_integration": "fab fa-whatsapp-square",
        "meta_integration.MetaAppConfig": "fas fa-cogs", "meta_integration.WebhookEventLog": "fas fa-history",
        "conversations": "fas fa-comments",
        "conversations.Contact": "fas fa-address-book", "conversations.Message": "fas fa-envelope",
        "flows": "fas fa-project-diagram",
        "flows.Flow": "fas fa-bezier-curve", "flows.FlowStep": "fas fa-shoe-prints",
        "flows.FlowTransition": "fas fa-route", "flows.ContactFlowState": "fas fa-map-signs",
        "customer_data": "fas fa-id-card", "customer_data.CustomerProfile": "fas fa-user-tag",
        "football_data_app": "fas fa-futbol",
        "football_data_app.League": "fas fa-trophy", "football_data_app.Team": "fas fa-shield-alt",
        "football_data_app.FootballFixture": "fas fa-calendar-alt", "football_data_app.Bookmaker": "fas fa-building",
        "football_data_app.MarketCategory": "fas fa-tags", "football_data_app.Market": "fas fa-store-alt",
        "football_data_app.MarketOutcome": "fas fa-poll-h", "football_data_app.UserWallet": "fas fa-wallet",
        "football_data_app.Transaction": "fas fa-exchange-alt", "football_data_app.Bet": "fas fa-ticket-alt",
        "football_data_app.BetSelection": "fas fa-check-double",
        "django_celery_beat": "fas fa-clock", "django_celery_beat.PeriodicTask": "fas fa-tasks",
        "django_celery_beat.IntervalSchedule": "fas fa-hourglass-half", "django_celery_beat.CrontabSchedule": "fas fa-calendar-day",
        "django_celery_beat.SolarSchedule": "fas fa-sun",
        "django_celery_results": "fas fa-database", "django_celery_results.TaskResult": "fas fa-check-circle",
    },
    "default_icon_parents": "fas fa-chevron-circle-right", "default_icon_children": "fas fa-circle",
    "related_modal_active": False, "show_ui_builder": False, "changeform_format": "horizontal_tabs",
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False, "footer_small_text": False, "body_small_text": False,
    "brand_small_text": False, "brand_colour": "navbar-success", "accent": "accent-teal",
    "navbar": "navbar-dark navbar-success", "no_navbar_border": False, "navbar_fixed": True,
    "layout_boxed": False, "footer_fixed": False, "sidebar_fixed": True,
    "sidebar": "sidebar-dark-success", "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False, "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False, "sidebar_nav_flat_style": False,
    "sidebar_nav_legacy_style": False, "sidebar_nav_accordion": True,
    "actions_sticky_top": True
}
