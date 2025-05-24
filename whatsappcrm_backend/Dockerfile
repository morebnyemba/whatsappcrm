# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies (if any, e.g., for PostgreSQL client)
# RUN apt-get update && apt-get install -y libpq-dev gcc

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code into the container
COPY . /app/

# Collect static files (if you're not serving them separately via Nginx/CDN in production)
# RUN python manage.py collectstatic --noinput

# Expose port (ensure this matches what Gunicorn/Daphne will run on)
EXPOSE 8000

# Command to run the application
# Replace 'whatsappcrm_backend.wsgi:application' with your actual WSGI application path
# For production, Gunicorn is a common choice. For Daphne (if using Channels for WebSockets), adjust accordingly.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "whatsappcrm_backend.wsgi:application"]