# Base image: Python 3.10 on Debian Buster (slim version)
FROM python:3.10-slim-buster

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE whatsappcrm_backend.settings
# Environment variables for Celery (can be overridden in docker-compose or .env)
ENV CELERY_BROKER_URL redis://redis:6379/0
ENV CELERY_RESULT_BACKEND django-db
ENV CELERY_WORKER_POOL gevent
ENV CELERY_WORKER_CONCURRENCY 100 # Default for gevent, adjust as needed

# Install system dependencies
# - build-essential & libpq-dev: for compiling Python packages like psycopg2
# - gettext: for Django's internationalization (makemessages)
# - netcat-traditional: for health checks/waiting for DB (optional in entrypoint)
# - curl: for debugging or health checks
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       gettext \
       netcat-traditional \
       curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
# Copy requirements first to leverage Docker cache
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy the entire project directory into the /app directory in the image
COPY . /app/

# Create directories for static and media files if they might not exist
# (collectstatic will create staticfiles, media_root should exist or be created by app logic/user)
# The actual MEDIA_ROOT is whatsapp_media_assets, which is copied with "COPY . /app/"
RUN mkdir -p /app/staticfiles
# Ensure the media directory defined in settings.MEDIA_ROOT exists
RUN mkdir -p /app/whatsapp_media_assets


# Optional: Create a non-root user and switch to it
# RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
# RUN chown -R appuser:appgroup /app
# USER appuser

# Expose the port Django will run on
EXPOSE 8000

# Run entrypoint script
ENTRYPOINT ["/entrypoint.sh"]

# Default command (can be overridden in docker-compose.yml)
CMD ["web"]
