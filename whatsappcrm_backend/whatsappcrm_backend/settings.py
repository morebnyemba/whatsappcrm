# whatsappcrm_backend/whatsappcrm_backend/settings.py

import os
from pathlib import Path
from datetime import timedelta
import dotenv # For loading .env file

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Environment Variables ---
# Load .env file from the project root
dotenv_file = BASE_DIR / '.env'
if os.path.isfile(dotenv_file):
    dotenv.load_dotenv(dotenv_file)

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-fallback-key-for-dev-only-replace-me-in-env') # Ensure this is in your .env

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True' # Default to True for dev if not set

ALLOWED_HOSTS_STRING = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,popular-real-squirrel.ngrok-free.app')
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_STRING.split(',') if host.strip()]

# --- CSRF Trusted Origins ---
# Add your ngrok URL and any other frontend domains that will make state-changing requests
# Ensure these are HTTPS if your site uses HTTPS.
CSRF_TRUSTED_ORIGINS_STRING = os.getenv('CSRF_TRUSTED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,https://popular-real-squirrel.ngrok-free.app')
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in CSRF_TRUSTED_ORIGINS_STRING.split(',') if origin.strip()]


# Application definition
INSTALLED_APPS = [
    'jazzmin', # Jazzmin must be before django.contrib.admin
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
'football_data_app.apps.FootballDataAppConfig',
    # Third-party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist', 
    'corsheaders',
    'django_celery_results',
    'django_celery_beat',
    'media_manager.apps.MediaManagerConfig',
    'django_extensions',

    # Our apps
    "stats",
    'meta_integration.apps.MetaIntegrationConfig',
    'conversations.apps.ConversationsConfig',
    'flows.apps.FlowsConfig',
    'customer_data.apps.CustomerDataConfig',
    "paynow_integration",# Ensure this is added if you have a Paynow integration app
    "referrals",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Serve static files in production
    'django.contrib.sessions.middleware.SessionMiddleware', 
    'corsheaders.middleware.CorsMiddleware', # Should be placed high
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
        'DIRS': [BASE_DIR / 'templates'], # Optional project-level templates
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
ASGI_APPLICATION = 'whatsappcrm_backend.asgi.application' # For Celery with Django 4+ (though not strictly needed for basic Celery worker)


# Database
DB_ENGINE_DEFAULT = 'django.db.backends.postgresql'
DB_NAME_DEFAULT = 'whatsapp_crm_dev'  # The database name you created
DB_USER_DEFAULT = 'crm_user'          # The user you created
DB_PASSWORD_DEFAULT = 'kayden'            # It's best to set this in your .env file
DB_HOST_DEFAULT = 'localhost'           # Or '127.0.0.1'
DB_PORT_DEFAULT = '5432'                # Default PostgreSQL port

DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', DB_ENGINE_DEFAULT),
        'NAME': os.getenv('DB_NAME', DB_NAME_DEFAULT),
        'USER': os.getenv('DB_USER', DB_USER_DEFAULT),
        'PASSWORD': os.getenv('DB_PASSWORD', DB_PASSWORD_DEFAULT), # Ensure this is in your .env!
        'HOST': os.getenv('DB_HOST', DB_HOST_DEFAULT),
        'PORT': os.getenv('DB_PORT', DB_PORT_DEFAULT),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Harare' 
USE_I18N = True
USE_TZ = True 

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/' 
STATIC_ROOT = BASE_DIR / 'staticfiles' # For production `collectstatic`

# Media files (User-uploaded content)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# WhiteNoise configuration for efficient static file serving in production
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Django REST Framework Settings ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication', # For browsable API & Django Admin
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated', # Default to requiring authentication
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20, 
}

# --- Simple JWT Settings ---
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.getenv('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', '60'))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.getenv('JWT_REFRESH_TOKEN_LIFETIME_DAYS', '7'))),
    'ROTATE_REFRESH_TOKENS': os.getenv('JWT_ROTATE_REFRESH_TOKENS', 'True') == 'True',
    'BLACKLIST_AFTER_ROTATION': os.getenv('JWT_BLACKLIST_AFTER_ROTATION', 'True') == 'True',
    'UPDATE_LAST_LOGIN': os.getenv('JWT_UPDATE_LAST_LOGIN', 'False') == 'True',
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY, 
    'VERIFYING_KEY': None, 
    'AUDIENCE': None, 'ISSUER': None, 'JWK_URL': None, 'LEEWAY': timedelta(seconds=0),
    'AUTH_HEADER_TYPES': ('Bearer',), 
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id', 'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type', 'JTI_CLAIM': 'jti',
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=int(os.getenv('JWT_SLIDING_TOKEN_LIFETIME_MINUTES', '5'))),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=int(os.getenv('JWT_SLIDING_TOKEN_REFRESH_LIFETIME_DAYS', '1'))),
}

# --- CORS Settings ---
CORS_ALLOWED_ORIGINS_STRING = os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,http://localhost,http://127.0.0.1,https://popular-real-squirrel.ngrok-free.app')
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS_STRING.split(',') if origin.strip()]
CORS_ALLOW_CREDENTIALS = True

# --- Celery Configuration ---
# Ensure your Redis server is running and accessible at this URL.
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://:@localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db' # Use a different DB for results
CELERY_ACCEPT_CONTENT = ['json'] # Content types to accept
CELERY_TASK_SERIALIZER = 'json'  # How tasks are serialized
CELERY_RESULT_SERIALIZER = 'json'# How results are serialized
CELERY_TIMEZONE = TIME_ZONE # Use Django's timezone (should be 'UTC')
CELERY_TASK_TRACK_STARTED = True # Optional: To track if a task has started
CELERY_TASK_TIME_LIMIT = int(os.getenv('CELERY_TASK_TIME_LIMIT_SECONDS', '1800')) # Optional: Hard time limit for tasks (e.g., 30 minutes)
CELERY_RESULT_EXTENDED = True
CELERY_CACHE_BACKEND = 'django-cache'


# For Celery Beat (scheduled tasks)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# --- Application-Specific Settings ---
CONVERSATION_EXPIRY_DAYS = int(os.getenv('CONVERSATION_EXPIRY_DAYS', '60'))

# --- Logging Configuration ---
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}', 'style': '{'},
        'simple': {'format': '[{asctime}] {levelname} {module} {message}', 'style': '{', 'datefmt': '%Y-%m-%d %H:%M:%S'},
    },
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'), 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'celery': {'handlers': ['console'], 'level': 'INFO', 'propagate': True},
        'meta_integration': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'conversations': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'flows': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'customer_data': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'football_data_app': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'football_data_app.tasks': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'football_data_app.tasks_apifootball': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'football_data_app.apifootball_client': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
        'football_data_app.the_odds_api_client': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': True},
    },
}


WHATSAPP_APP_SECRET = os.getenv('WHATSAPP_APP_SECRET', None)
# --- Jazzmin Admin Theme Settings ---
JAZZMIN_SETTINGS = {
    "site_title": "AutoWhasapp",
    "site_header": "AutoWhatsapp",
    "site_brand": "A-W",
    "site_logo_classes": "img-circle",
    # "site_logo": "path/to/your/logo.png", # Optional: Add your logo
    "welcome_sign": "Welcome to the AutoWhatsapp Admin",
    "copyright": "Slyker Tech Web Services.",
    "search_model": ["auth.User", "meta_integration.MetaAppConfig", "conversations.Contact", "flows.Flow"],
    "user_avatar": None,
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"model": "auth.User"},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],
    "icons": {
        "football_data_app": "fas fa-football", # Example icon
         "football_data_app.FootballFixture": "fas fa-calendar-alt",
        "auth": "fas fa-users-cog", "auth.user": "fas fa-user", "auth.Group": "fas fa-users",
        "meta_integration": "fab fa-whatsapp-square",
        "meta_integration.MetaAppConfig": "fas fa-cogs", "meta_integration.WebhookEventLog": "fas fa-history",
        "conversations": "fas fa-comments",
        "conversations.Contact": "fas fa-address-book", "conversations.Message": "fas fa-envelope",
        "flows": "fas fa-project-diagram",
        "flows.Flow": "fas fa-bezier-curve", "flows.FlowStep": "fas fa-shoe-prints",
        "flows.FlowTransition": "fas fa-route", "flows.ContactFlowState": "fas fa-map-signs",
        "customer_data": "fas fa-id-card", "customer_data.CustomerProfile": "fas fa-user-tag",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    "related_modal_active": False,
    "show_ui_builder": False, # Set to True in dev to customize Jazzmin theme via UI
    "changeform_format": "horizontal_tabs",
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

# Ensure your .env file has DJANGO_SECRET_KEY and other sensitive variables.
# Example .env content (should be in a separate .env file at project root):
# DJANGO_SECRET_KEY="your-actual-strong-secret-key-here"
# DJANGO_DEBUG="True" # Set to "False" for production
# DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,yourdomain.com,popular-real-squirrel.ngrok-free.app"
# CSRF_TRUSTED_ORIGINS="http://localhost:5173,https://popular-real-squirrel.ngrok-free.app"
# CORS_ALLOWED_ORIGINS="http://localhost:5173,http://127.0.0.1:5173,http://localhost,http://127.0.0.1,https://popular-real-squirrel.ngrok-free.app"
# CELERY_BROKER_URL="redis://localhost:6379/0"
# CELERY_RESULT_BACKEND="redis://localhost:6379/1"
# DB_ENGINE="django.db.backends.postgresql" # Or your preferred DB
# DB_NAME="your_db_name"
# DB_USER="your_db_user"
# DB_PASSWORD="your_db_password"
# DB_HOST="localhost"
# DB_PORT="5432"
# CONVERSATION_EXPIRY_DAYS="60"
# JWT_ACCESS_TOKEN_LIFETIME_MINUTES="60"
# JWT_REFRESH_TOKEN_LIFETIME_DAYS="7"
# --- Football Data API Configuration ---

# APIFootball.com (Primary Provider)
API_FOOTBALL_KEY = os.environ.get('API_FOOTBALL_KEY')

# APIFootball Operational Parameters
APIFOOTBALL_LEAD_TIME_DAYS = 7  # How many days ahead to fetch fixtures
APIFOOTBALL_EVENT_DISCOVERY_STALENESS_HOURS = 6  # Hours before refetching events
APIFOOTBALL_UPCOMING_STALENESS_MINUTES = 60  # Minutes before refetching odds
APIFOOTBALL_ASSUMED_COMPLETION_MINUTES = 120  # Minutes after scheduled start to assume completion

# Legacy The Odds API Configuration (Backup - kept for reference)
THE_ODDS_API_KEY = os.environ.get('THE_ODDS_API_KEY')
THE_ODDS_API_TARGET_BOOKMAKER = 'pinnacle'
THE_ODDS_API_LEAD_TIME_DAYS = 7
THE_ODDS_API_DEFAULT_REGIONS = "uk,eu,us,au"
THE_ODDS_API_DEFAULT_MARKETS = "h2h,totals"
THE_ODDS_API_ADDITIONAL_MARKETS = "alternate_totals,btts"
THE_ODDS_API_PREFERRED_BOOKMAKERS = "bet365"
THE_ODDS_API_EVENT_DISCOVERY_STALENESS_HOURS = 6
THE_ODDS_API_UPCOMING_STALENESS_MINUTES = 60
THE_ODDS_API_ASSUMED_COMPLETION_MINUTES = 120
THE_ODDS_API_MAX_EVENT_RETRIES = 3
THE_ODDS_API_EVENT_RETRY_DELAY = 300