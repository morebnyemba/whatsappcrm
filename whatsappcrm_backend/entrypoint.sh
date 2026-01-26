#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Clean up stale Python bytecode in migrations to prevent import errors
# This is critical when using volume mounts in development
# The cleanup is comprehensive to prevent NodeNotFoundError issues where Django
# can't find migration files due to stale bytecode taking precedence
cleanup_migration_cache() {
    echo "Cleaning up migration __pycache__ directories and bytecode files..."
    
    # Remove all __pycache__ directories under migrations folders
    find /app -type d -name "__pycache__" -path "*/migrations/*" -exec rm -rf {} + 2>/dev/null || true
    
    # Also remove any stray .pyc and .pyo files directly in migrations directories
    # (in case they exist outside of __pycache__ for some reason)
    find /app -type f \( -name "*.pyc" -o -name "*.pyo" \) -path "*/migrations/*" -delete 2>/dev/null || true
    
    # Ensure Python doesn't write new bytecode during this run
    # This is already set in Dockerfile but we reinforce it here
    export PYTHONDONTWRITEBYTECODE=1
    
    echo "Migration cache cleanup complete."
}

# Verify that critical migration files exist before running migrations
# This helps catch deployment issues early with a clear error message
verify_migrations() {
    echo "Verifying migration files..."
    
    # Check that all migration directories have an __init__.py
    migration_dirs=$(find /app -type d -name "migrations" 2>/dev/null)
    for dir in $migration_dirs; do
        if [ -d "$dir" ] && [ ! -f "$dir/__init__.py" ]; then
            echo "WARNING: Missing __init__.py in $dir"
        fi
    done
    
    # List migration files for debugging
    echo "Found migration files in conversations app:"
    ls -la /app/conversations/migrations/*.py 2>/dev/null || echo "  (migrations directory not found at expected location)"
    
    echo "Migration verification complete."
}

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

# Always clean migration cache before starting any service to prevent stale bytecode issues
cleanup_migration_cache

if [ "$COMMAND" = "web" ] || [ "$COMMAND" = "celerybeat" ]; then
    wait_for_db
    verify_migrations
    run_migrations
fi

if [ "$COMMAND" = "web" ]; then
    collect_static # Only web service needs to collect static files typically
    echo "Starting Gunicorn server on 0.0.0.0:8000..."
    # Use Gunicorn for production with WhiteNoise serving static files
    exec gunicorn --workers=3 --bind 0.0.0.0:8000 whatsappcrm_backend.wsgi:application "$@"

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
