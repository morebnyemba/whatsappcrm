# Database Reset Commands - Quick Reference

This guide provides Docker Compose commands to clear the database and migrations for the WhatsApp CRM project.

## ⚠️ WARNING

**These commands will DELETE ALL DATA in your database!** Always backup before proceeding.

## Quick Backup

```bash
# Backup your database first
./backup_database.sh
```

## Option 1: Using the Reset Script (Recommended)

The easiest way to reset migrations and database:

```bash
# This will auto-detect your environment and guide you through
./reset_migrations.sh
```

## Option 2: Manual Docker Compose Commands

### Stop All Services

```bash
# Stop all containers
docker compose down
```

### Clear Database and Redis Data

```bash
# Stop and remove all containers, networks, and volumes
docker compose down -v

# This removes:
# - All containers
# - Named volumes (postgres_data, redis_data, etc.)
# - Networks created by docker-compose
```

### Start Fresh

```bash
# Start the database and Redis services
docker compose up -d db redis

# Wait for services to be ready (about 10-15 seconds)
sleep 15

# Start the backend (will run migrations automatically)
docker compose up -d backend

# View logs to ensure migrations ran successfully
docker compose logs -f backend
```

### Alternative: Keep Data, Reset Migrations Only

If you want to keep your data but reset migrations:

```bash
# 1. Stop backend services
docker compose stop backend celery_io_worker celery_cpu_worker celery_beat

# 2. Clear database tables in one command
docker compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO crm_user; GRANT ALL ON SCHEMA public TO public;"

# Alternatively, access the database shell interactively:
# docker compose exec db psql -U crm_user -d whatsapp_crm_dev
# Then run the following SQL commands:
#   DROP SCHEMA public CASCADE;
#   CREATE SCHEMA public;
#   GRANT ALL ON SCHEMA public TO crm_user;
#   GRANT ALL ON SCHEMA public TO public;
#   \q

# 3. Remove migration files from your local machine
find whatsappcrm_backend/*/migrations -type f -name "*.py" ! -name "__init__.py" -delete

# 4. Start backend to create fresh migrations
docker compose up -d backend

# 5. Create fresh migrations
docker compose exec backend python manage.py makemigrations

# 6. Apply migrations
docker compose exec backend python manage.py migrate

# 7. Create superuser
docker compose exec backend python manage.py createsuperuser
```

## Common Docker Compose Commands

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f db
docker compose logs -f redis

# Last 100 lines
docker compose logs --tail=100 backend
```

### Check Service Status

```bash
# List all services and their status
docker compose ps

# Check if database is ready
docker compose exec db pg_isready -U crm_user
```

### Execute Commands in Containers

```bash
# Run Django management commands
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py collectstatic --noinput

# Access Django shell
docker compose exec backend python manage.py shell

# Access database shell
docker compose exec db psql -U crm_user -d whatsapp_crm_dev

# Access Redis CLI (replace YOUR_PASSWORD with actual Redis password)
docker compose exec redis redis-cli -a YOUR_PASSWORD

# Or read password from .env and use it
docker compose exec redis redis-cli -a $(grep REDIS_PASSWORD .env | cut -d '=' -f2)
```

### Restart Services

```bash
# Restart all services
docker compose restart

# Restart specific service
docker compose restart backend
docker compose restart celery_io_worker
```

### Rebuild Containers

```bash
# Rebuild and restart (useful after code changes)
docker compose up -d --build

# Rebuild specific service
docker compose up -d --build backend
```

### Clean Up Everything

```bash
# Nuclear option: Remove everything including images
docker compose down -v --rmi all

# Then start fresh
docker compose up -d
```

## Troubleshooting Common Issues

### Issue: "App is not starting"

**Solution:**

```bash
# Check logs for errors
docker compose logs backend

# Common fixes:
# 1. Clear volumes and restart
docker compose down -v
docker compose up -d

# 2. Rebuild containers
docker compose up -d --build
```

### Issue: Migration conflicts

**Solution:**

```bash
# Use the reset script
./reset_migrations.sh

# Or manually:
# 1. Stop services
docker compose down

# 2. Remove volumes
docker volume rm whatsappcrm_postgres_data whatsappcrm_redis_data

# 3. Start fresh
docker compose up -d
```

### Issue: "Database connection failed"

**Solution:**

```bash
# Check if database is running
docker compose ps db

# Check database logs
docker compose logs db

# Verify database is ready
docker compose exec db pg_isready -U crm_user

# If not ready, restart
docker compose restart db
sleep 10
docker compose restart backend
```

### Issue: Permission errors

**Solution:**

```bash
# Fix file permissions
sudo chown -R $USER:$USER whatsappcrm_backend/

# Restart services
docker compose restart
```

## Environment Variables

Make sure your `.env` file has the correct database settings:

```env
# Database Configuration
DB_ENGINE=django.db.backends.postgresql
DB_NAME=whatsapp_crm_dev
DB_USER=crm_user
DB_PASSWORD=your_secure_password_here
DB_HOST=db
DB_PORT=5432

# Redis Configuration
REDIS_PASSWORD=your_redis_password_here
REDIS_HOST=redis
REDIS_PORT=6379

# Celery Configuration
CELERY_BROKER_URL=redis://:your_redis_password_here@redis:6379/0
CELERY_RESULT_BACKEND=redis://:your_redis_password_here@redis:6379/0
```

**Note:** Replace `your_redis_password_here` with your actual Redis password in all occurrences.

## Step-by-Step: Complete Fresh Start

If you want to start completely fresh:

```bash
# 1. Backup (if needed)
./backup_database.sh

# 2. Stop and remove everything
docker compose down -v

# 3. Clean Docker system (optional, removes unused images/containers)
docker system prune -f

# 4. Start database and redis
docker compose up -d db redis

# 5. Wait for services to be ready
sleep 15

# 6. Start backend (migrations will run automatically via entrypoint.sh)
docker compose up -d backend

# 7. Check logs
docker compose logs -f backend

# 8. Once migrations complete, create superuser
docker compose exec backend python manage.py createsuperuser

# 9. Start remaining services
docker compose up -d
```

## Quick Commands Reference

| Action | Command |
|--------|---------|
| Start all services | `docker compose up -d` |
| Stop all services | `docker compose down` |
| View logs | `docker compose logs -f` |
| Reset everything | `docker compose down -v && docker compose up -d` |
| Run migrations | `docker compose exec backend python manage.py migrate` |
| Create migrations | `docker compose exec backend python manage.py makemigrations` |
| Create superuser | `docker compose exec backend python manage.py createsuperuser` |
| Database shell | `docker compose exec db psql -U crm_user -d whatsapp_crm_dev` |
| Django shell | `docker compose exec backend python manage.py shell` |
| Rebuild backend | `docker compose up -d --build backend` |

## Notes

- Docker Compose V2 uses `docker compose` (space) instead of `docker-compose` (hyphen)
- The `entrypoint.sh` script automatically runs migrations when the backend starts
- Always check logs if something doesn't work: `docker compose logs -f backend`
- The database volume persists data between container restarts
- Use `docker compose down -v` to remove volumes and start with a clean database

## Support

If you encounter issues:
1. Check the logs: `docker compose logs -f`
2. Verify services are running: `docker compose ps`
3. Check database connection: `docker compose exec db pg_isready`
4. Review the `.env` file for correct configuration
5. Try the reset script: `./reset_migrations.sh`
