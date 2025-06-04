# Use an official Python runtime as a parent image
FROM python:3.10-slim-buster

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE whatsappcrm_backend.settings # Good practice to set a default

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
RUN mkdir -p /app/staticfiles
RUN mkdir -p /app/whatsapp_media_assets # Assuming this is your MEDIA_ROOT

# Expose port (ensure this matches what Gunicorn/Daphne will run on)
EXPOSE 8000

# Command to run the application (default for services using this image, like 'backend')
# This will be overridden by the 'command' in docker-compose.yml for celery_worker and celery_beat.
# Ensure 'gunicorn' is in your requirements.txt if this CMD is used.
CMD ["gunicorn", "--workers=3", "--bind", "0.0.0.0:8000", "whatsappcrm_backend.wsgi:application"]
