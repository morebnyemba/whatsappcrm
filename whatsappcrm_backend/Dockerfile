# Use an official Python runtime as a parent image
FROM python:3.10-slim-buster # Using slim-buster for broader package availability

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE whatsappcrm_backend.settings # Good to set default

# Set work directory
WORKDIR /app

# Install system dependencies
# - build-essential & libpq-dev: for compiling Python packages like psycopg2, gevent
# - gettext: for Django's internationalization (makemessages)
# - netcat-traditional: for 'nc' command, used in your celery_worker command for waiting
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       gettext \
       netcat-traditional \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
# It's good practice to upgrade pip first
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code into the container
COPY . /app/

# Create directories for static and media files if needed by any process
# These directories will be populated by collectstatic or app uploads
# and can be mounted to volumes.
RUN mkdir -p /app/staticfiles
RUN mkdir -p /app/whatsapp_media_assets # Assuming this is your MEDIA_ROOT

# Expose port (ensure this matches what your web server will run on)
EXPOSE 8000

# CMD to run the application (this is the default if no command is specified in docker-compose for a service)
# If you want to use Gunicorn for your 'backend' web service.
# Ensure 'gunicorn' is in your requirements.txt
# This CMD will be overridden by the 'command' in your docker-compose.yml for celery_worker and celery_beat.
# If you use an entrypoint.sh, this CMD might be an argument to it.
CMD ["gunicorn", "--workers=3", "--bind", "0.0.0.0:8000", "whatsappcrm_backend.wsgi:application"]
