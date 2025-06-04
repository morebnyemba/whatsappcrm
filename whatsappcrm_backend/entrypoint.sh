#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Function to wait for PostgreSQL to be available
wait_for_db() {
    echo "Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
    # Use environment variables for DB host and port, with defaults
    # These should be set in the Docker environment (e.g., via docker-compose .env file)
    target_host=${DB_HOST:-db}
    target_port=${DB_PORT:-5432}

    # Loop until connection is successful or timeout
    timeout=60 # seconds
    start_time=$(date +%s)
    while ! nc -z "$target_host" "$target_port"; do
        current_time=$(date +%s)
        elapsed_time=$((current_time - start_time))
        if [ "$elapsed_time" -ge "$timeout" ]; then
            echo "Timeout waiting for PostgreSQL."
            exit 1
        fi
        echo "PostgreSQL is unavailable - sleeping"
        sleep 1
    done
    echo "PostgreSQL is up - executing command"
}

# Apply database migrations
run_migrations() {
    echo "Applying database migrations..."
    python manage.py migrate --noinput
}

# Collect static files
collect_static() {
    echo "Collecting static files..."
    # --clear ensures old files are removed
    python manage.py collectstatic --noinput --clear
}


# Get the command to run (web, celeryworker, celerybeat, or custom)
COMMAND="$1"
# Shift arguments so that $@ contains arguments for the command itself
shift


# Execute pre-run commands (migrations, collectstatic) only if appropriate
# For example, Celery workers don't need to run collectstatic repeatedly.
# Migrations should ideally be run by one service instance, or as a separate step/job in CI/CD.
# For simplicity here, 'web' service will handle migrations and collectstatic.
# Celery beat also needs migrations for django_celery_beat tables.

if [ "$COMMAND" = "web" ] || [ "$COMMAND" = "celerybeat" ]; then
    wait_for_db
    run_migrations
fi

if [ "$COMMAND" = "web" ]; then
    collect_static # Only web service needs to collect static files typically
    echo "Starting Django development server on 0.0.0.0:8000..."
    # Django's runserver will serve static and media files if DEBUG=True and urls.py is configured.
    # For production, use Gunicorn/uWSGI and Nginx/Cloudfront for static/media.
    exec python manage.py runserver 0.0.0.0:8000 "$@"

elif [ "$COMMAND" = "celeryworker" ]; then
    wait_for_db # Worker might need DB access for some initializations or tasks
    echo "Starting Celery worker..."
    # Use environment variables for pool and concurrency, with defaults.
    # These are set in Dockerfile ENV or overridden by docker-compose environment.
    # Default to gevent and a high concurrency for I/O bound tasks.
    POOL=${CELERY_WORKER_POOL:-gevent}
    CONCURRENCY=${CELERY_WORKER_CONCURRENCY:-100} # Default for gevent/eventlet
    
    if [ "$POOL" = "prefork" ]; then
        # For prefork, concurrency often matches CPU cores.
        CONCURRENCY=${CELERY_WORKER_CONCURRENCY:-$(nproc --all || echo 4)} # Default to num cores or 4
    fi
    
    echo "Using Celery Pool: $POOL, Concurrency: $CONCURRENCY"
    # -E for events, useful for monitoring.
    # --without-gossip, --without-mingle, --without-heartbeat can reduce network chattiness for workers if not using advanced features.
    exec celery -A whatsappcrm_backend.celery worker -l INFO -P "$POOL" -c "$CONCURRENCY" --without-gossip --without-mingle --without-heartbeat -E "$@"

elif [ "$COMMAND" = "celerybeat" ]; then
    # wait_for_db and run_migrations already called above for celerybeat
    echo "Starting Celery beat scheduler..."
    # Remove Celery beat PID file if it exists to prevent startup issues
    rm -f /app/celerybeat.pid # Path inside the container, relative to WORKDIR
    exec celery -A whatsappcrm_backend.celery beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler --pidfile=/app/celerybeat.pid "$@"

else
    # If an unknown command or custom command is provided
    echo "Executing custom command: $COMMAND $@"
    exec "$COMMAND" "$@"
fi
