# Use an official Python runtime as a parent image
# Use "bullseye" which is a more recent and supported Debian version than "buster".
FROM python:3.10-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Good practice to set a default settings module
ENV DJANGO_SETTINGS_MODULE=whatsappcrm_backend.settings

# Set work directory
WORKDIR /app

# Install system dependencies
# - build-essential & libpq-dev: for compiling Python packages like psycopg2, gevent
# - gettext: for Django's internationalization (makemessages)
# - netcat-traditional: for 'nc' command, used in docker-compose celery_worker command
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       gettext \
       netcat-traditional \
       curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code into the container
COPY . /app/

# Create directories that might be needed for volumes or collectstatic
# and change ownership to the new user
RUN mkdir -p /app/staticfiles
RUN mkdir -p /app/whatsapp_media_assets # Assuming this is your MEDIA_ROOT

# Expose port (ensure this matches what Gunicorn/Daphne will run on)
EXPOSE 8000

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Add a healthcheck to ensure the application is running correctly.
# This command will be run inside the container to check its health.
# The /admin/login/ endpoint is a good default as it's lightweight.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/admin/login/ || exit 1

# Set entrypoint to use the entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]

# Command to run the application (default for services using this image, like 'backend')
# This will be overridden by the 'command' in docker-compose.yml for celery_worker and celery_beat.
CMD ["web"]
