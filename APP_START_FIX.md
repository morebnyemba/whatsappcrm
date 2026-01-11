# Fix for App Not Starting - Database and Migration Reset

## Issue Summary

The WhatsApp CRM application is failing to start with errors related to migrations or database initialization. The error logs show:

```
[2026-01-10 08:24:32] INFO tasks API-Football v3 tasks successfully loaded and available.
Traceback (most recent call last):
  File "/app/manage.py", line 22, in
```

## Root Cause

The incomplete traceback suggests the application is crashing during Django initialization, likely due to:
1. Migration conflicts or corrupted migration files
2. Database schema inconsistencies
3. Missing or stale migration __pycache__ files

## Solution: Start Fresh

You requested Docker Compose commands to clear the database and migrations. Here are the recommended approaches:

### Option 1: Quick Reset (Recommended) ⭐

Use the automated reset script that handles everything for you:

```bash
./reset_migrations.sh
```

This script will:
- Auto-detect your Docker environment
- Clear all database tables
- Remove migration files
- Create fresh migrations
- Apply migrations
- Prompt you to create a superuser

### Option 2: Manual Docker Compose Commands

If you prefer manual control, follow these steps:

#### Complete Fresh Start (Removes All Data)

```bash
# 1. Stop all services and remove volumes
docker compose down -v

# 2. Start services fresh
docker compose up -d

# 3. Wait for initialization (30-60 seconds)
sleep 30

# 4. Check logs
docker compose logs -f backend

# 5. Create superuser once backend is ready
docker compose exec backend python manage.py createsuperuser
```

#### Reset Migrations While Keeping Some Data

```bash
# 1. Stop services (but keep volumes)
docker compose stop backend celery_io_worker celery_cpu_worker celery_beat

# 2. Clear database tables
docker compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO crm_user; GRANT ALL ON SCHEMA public TO public;"

# 3. Remove migration files (from your local machine)
find whatsappcrm_backend/*/migrations -type f -name "*.py" ! -name "__init__.py" -delete

# 4. Start backend to regenerate migrations
docker compose up -d backend

# 5. Create and apply migrations
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate

# 6. Create superuser
docker compose exec backend python manage.py createsuperuser
```

## Quick Commands for Common Tasks

### View Logs (Essential for Debugging)

```bash
# Follow backend logs in real-time
docker compose logs -f backend

# View last 100 lines
docker compose logs --tail=100 backend

# View all services
docker compose logs -f
```

### Check Service Status

```bash
# List all services
docker compose ps

# Check if database is ready
docker compose exec db pg_isready -U crm_user
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart backend
```

### Database Operations

```bash
# Access database shell
docker compose exec db psql -U crm_user -d whatsapp_crm_dev

# Run migrations manually
docker compose exec backend python manage.py migrate

# Show migration status
docker compose exec backend python manage.py showmigrations
```

## Verification Steps

After resetting, verify everything is working:

1. **Check backend is running:**
   ```bash
   docker compose ps backend
   ```
   Status should be "Up"

2. **Verify migrations ran:**
   ```bash
   docker compose logs backend | grep "Applying"
   ```
   You should see "Applying [app_name].[migration_name]..." messages

3. **Check database connection:**
   ```bash
   docker compose exec backend python manage.py check --database default
   ```
   Should show "System check identified no issues"

4. **Test API:**
   ```bash
   curl http://localhost:8000/crm-api/
   ```
   Should return API response (not error)

## Troubleshooting

### If Backend Keeps Restarting

```bash
# Check logs for specific error
docker compose logs backend

# Common fixes:
# 1. Ensure .env file exists with correct values
# 2. Verify database is ready: docker compose exec db pg_isready
# 3. Clear volumes: docker compose down -v && docker compose up -d
```

### If Migrations Fail

```bash
# Show migration plan
docker compose exec backend python manage.py showmigrations

# Try fake initial migration
docker compose exec backend python manage.py migrate --fake-initial

# If still failing, use reset script
./reset_migrations.sh
```

### If Database Connection Fails

```bash
# Check database is running
docker compose ps db

# Check database health
docker compose logs db

# Restart database
docker compose restart db
sleep 10
docker compose restart backend
```

## Important Notes

- ⚠️ **Data Loss Warning**: `docker compose down -v` will DELETE ALL DATA including database
- 📦 **Backup First**: Always backup before major operations: `./backup_database.sh`
- 🔄 **Wait Time**: Give services 30-60 seconds to initialize after starting
- 📝 **Environment Variables**: Ensure `.env` file is properly configured
- 🐳 **Docker Compose V2**: Use `docker compose` (space) not `docker-compose` (hyphen)

## Additional Resources

For more detailed information, see:

- **[DOCKER_QUICK_START.md](DOCKER_QUICK_START.md)** - Quick reference for Docker commands
- **[DATABASE_RESET_COMMANDS.md](DATABASE_RESET_COMMANDS.md)** - Comprehensive database operations guide
- **[MIGRATION_RESET_GUIDE.md](MIGRATION_RESET_GUIDE.md)** - Detailed migration reset documentation
- **[README.md](README.md)** - Complete project documentation

## Quick Answer to Your Request

You asked: "give docker compose commands to clear the database and migration"

**Answer:**

```bash
# Complete reset (removes all data):
docker compose down -v
docker compose up -d

# Or use the automated script:
./reset_migrations.sh
```

Both approaches will:
1. Clear the database
2. Remove migration conflicts
3. Create fresh migrations
4. Start the app cleanly

The script method is recommended as it's safer and more comprehensive.
