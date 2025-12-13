# Docker Exec Commands for Database and Migration Reset

This guide provides the specific Docker exec commands needed to drop all database data, delete migrations, create new migrations, and apply them.

## ⚠️ CRITICAL WARNING

**These commands will PERMANENTLY DELETE ALL DATA in your database!**

- Always backup your database before proceeding
- Only run these commands in development environments
- All existing data will be lost and cannot be recovered without a backup
- Make sure you understand each command before executing it

## Prerequisites

1. **Docker and Docker Compose must be installed and running**
2. **All containers should be running**: `docker-compose up -d`
3. **Create a backup first** (see Backup section below)

## ⚠️ IMPORTANT: You MUST Run ALL Steps in Order!

**DO NOT skip Step 3 (Drop Database Tables)!**

If you skip the database drop step and only delete migrations, you will get errors like:
```
psycopg2.errors.DuplicateColumn: column "triggered_by_flow_step_id" of relation "conversations_message" already exists
```

This happens because the old database tables still exist, and Django tries to create columns that are already there.

**The correct order is:**
1. Backup → 2. Stop services → 3. Drop database → 4. Start services → 5. Delete migrations → 6. Create migrations → 7. Apply migrations → 8. Create superuser → 9. Restart services

## Quick Reference - Complete Reset Process

**⚠️ RUN ALL COMMANDS IN ORDER - DO NOT SKIP ANY STEPS!**

```bash
# 1. BACKUP YOUR DATABASE FIRST!
docker-compose exec db pg_dump -U crm_user whatsapp_crm_dev > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Stop backend services to avoid connection issues
docker-compose stop backend celery_worker celery_worker_football celery_beat

# 3. ⚠️ CRITICAL: Drop all tables in the database (DO NOT SKIP THIS STEP!)
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO crm_user; GRANT ALL ON SCHEMA public TO public;"

# 4. Start backend service
docker-compose start backend

# Wait for backend to be fully ready (adjust timing if needed)
sleep 10

# For more reliability, see alternative wait methods in detailed guide below

# 5. Delete all migration files (inside backend container)
docker-compose exec backend bash -c "find /app -path '*/migrations/*.py' -not -path '*/migrations/__init__.py' -delete && find /app -path '*/migrations/*.pyc' -delete"

# 6. Create new migrations
docker-compose exec backend python manage.py makemigrations

# 7. Apply migrations
docker-compose exec backend python manage.py migrate

# 8. Create superuser
docker-compose exec backend python manage.py createsuperuser

# 9. Restart all services
docker-compose restart backend celery_worker celery_worker_football celery_beat
```

## Alternative: One-Line Command (For Advanced Users)

If you want to run all the critical steps in one go (after backup), use this command:

**Note:** Adjust the `sleep 10` duration if your backend takes longer to start (check with `docker-compose logs backend --tail=20`).

```bash
docker-compose stop backend celery_worker celery_worker_football celery_beat && \
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO crm_user; GRANT ALL ON SCHEMA public TO public;" && \
docker-compose start backend && \
sleep 10 && \
docker-compose exec backend bash -c "find /app -path '*/migrations/*.py' -not -path '*/migrations/__init__.py' -delete && find /app -path '*/migrations/*.pyc' -delete" && \
docker-compose exec backend python manage.py makemigrations && \
docker-compose exec backend python manage.py migrate && \
docker-compose restart backend celery_worker celery_worker_football celery_beat
```

**Important:** 
- This command chains all steps together. If any step fails, the subsequent steps won't run.
- Create your backup first!
- If the backend takes longer than 10 seconds to start, the command may fail. Increase the sleep duration or run steps individually.

## Detailed Step-by-Step Guide

### Step 1: Backup Your Database

**ALWAYS backup before proceeding!**

```bash
# Create a backup with timestamp
docker-compose exec db pg_dump -U crm_user whatsapp_crm_dev > backup_$(date +%Y%m%d_%H%M%S).sql

# Or use the backup script if available
./backup_database.sh
```

**Verify backup was created:**
```bash
ls -lh backup_*.sql
```

### Step 2: Stop Backend Services

Stop services that are connected to the database to avoid connection errors:

```bash
docker-compose stop backend celery_worker celery_worker_football celery_beat
```

**Verify services are stopped:**
```bash
docker-compose ps
```

### Step 3: Drop All Database Tables

**⚠️ THIS IS THE MOST CRITICAL STEP - DO NOT SKIP!**

**Option A: Drop and Recreate Schema (Recommended)**

This is the cleanest method - it drops the entire schema and recreates it, removing ALL tables, views, indexes, constraints, sequences, and relations:

```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO crm_user; GRANT ALL ON SCHEMA public TO public;"
```

**What this command does:**
- `DROP SCHEMA public CASCADE` - Removes the entire public schema and ALL objects in it (tables, indexes, constraints, sequences, etc.)
- `CREATE SCHEMA public` - Creates a fresh, empty public schema
- `GRANT ALL` - Restores permissions for the database user

**Option B: Drop All Tables Individually**

This method keeps the schema but drops all tables:

```bash
# Generate and execute DROP TABLE commands
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "
DO \$\$ DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END \$\$;
"
```

**Verify all tables are dropped:**
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "\dt"
```

You should see "Did not find any relations" or an empty list.

### Step 4: Start Backend Service

```bash
docker-compose start backend

# Wait for backend to be ready
# The backend needs time to initialize Django before accepting management commands
sleep 10
```

**Note:** If your backend takes longer to start, increase the sleep duration. You can check startup status with:
```bash
docker-compose logs backend --tail=20
```

**Alternative wait method (more reliable):**
```bash
# Keep trying until Django is ready
until docker-compose exec backend python -c "import django; django.setup()" 2>/dev/null; do
  echo "Waiting for backend..."
  sleep 2
done
echo "Backend is ready!"
```

### Step 5: Delete All Migration Files

Delete all migration files except `__init__.py`:

```bash
docker-compose exec backend bash -c "find /app -path '*/migrations/*.py' -not -path '*/migrations/__init__.py' -delete"
```

**Also delete compiled Python files:**
```bash
docker-compose exec backend bash -c "find /app -path '*/migrations/*.pyc' -delete"
docker-compose exec backend bash -c "find /app -path '*/migrations/__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true"
```

**Verify migration files are deleted:**
```bash
docker-compose exec backend bash -c "find /app -path '*/migrations/*.py' -not -path '*/migrations/__init__.py'"
```

This should return no results.

### Step 6: Create New Migrations

Generate fresh migration files for all Django apps:

```bash
docker-compose exec backend python manage.py makemigrations
```

**Expected output:**
```
Migrations for 'conversations':
  conversations/migrations/0001_initial.py
    - Create model Contact
    - Create model Message
    ...
Migrations for 'customer_data':
  customer_data/migrations/0001_initial.py
    ...
```

**If you see "No changes detected":**
- Make sure the migration files were actually deleted
- Check that your models are properly defined
- Try specifying apps individually: `docker-compose exec backend python manage.py makemigrations conversations customer_data flows ...`

### Step 7: Apply Migrations

Apply all migrations to rebuild the database schema:

```bash
docker-compose exec backend python manage.py migrate
```

**Expected output:**
```
Operations to perform:
  Apply all migrations: admin, auth, contenttypes, sessions, conversations, customer_data, flows, ...
Running migrations:
  Applying contenttypes.0001_initial... OK
  Applying auth.0001_initial... OK
  ...
```

**Verify database tables:**
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "\dt"
```

You should see all your application tables listed.

### Step 8: Create Superuser

Create a Django admin superuser account:

```bash
docker-compose exec backend python manage.py createsuperuser
```

Follow the prompts to enter:
- Username
- Email address
- Password

### Step 9: Restart All Services

Restart services to ensure all are using the new database schema:

```bash
docker-compose restart backend celery_worker celery_worker_football celery_beat
```

**Or restart everything:**
```bash
docker-compose restart
```

### Step 10: Verify Everything Works

**Check service status:**
```bash
docker-compose ps
```

All services should show "Up" status.

**Check Django migrations:**
```bash
docker-compose exec backend python manage.py showmigrations
```

All migrations should have `[X]` indicating they're applied.

**Test the admin interface:**
- Navigate to http://localhost:8000/admin
- Log in with your superuser credentials

**Check Celery workers:**
```bash
docker-compose logs -f celery_worker --tail=50
```

Look for successful startup messages.

## Alternative: Using the Reset Script

If you prefer, you can use the existing reset script:

```bash
# Using the wrapper script (automatically detects Docker)
./reset_migrations.sh

# Or run Python script directly in container
docker-compose exec backend python /tmp/reset_migrations.py
```

See [MIGRATION_RESET_GUIDE.md](MIGRATION_RESET_GUIDE.md) for details.

## Troubleshooting

### "DuplicateColumn" or "already exists" errors during migration

**Error message:**
```
psycopg2.errors.DuplicateColumn: column "triggered_by_flow_step_id" of relation "conversations_message" already exists
```

**Cause:** You skipped Step 3 (dropping the database) and only deleted migration files. The old database tables still exist with their columns, so Django tries to create columns that are already there.

**Solution:**

You MUST drop the database tables before creating new migrations. Run these commands:

```bash
# 1. Stop all backend services
docker-compose stop backend celery_worker celery_worker_football celery_beat

# 2. Drop the entire database schema (THIS IS THE KEY STEP!)
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO crm_user; GRANT ALL ON SCHEMA public TO public;"

# 3. Verify all tables are gone
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "\dt"
# You should see "Did not find any relations"

# 4. Start backend service
docker-compose start backend
sleep 10

# 5. Now apply the migrations you already created
docker-compose exec backend python manage.py migrate

# 6. Restart all services
docker-compose restart
```

**Important:** The database drop command removes ALL tables, indexes, constraints, and relations. This is necessary for a clean slate.

### "Database is being accessed by other users"

If you get this error when trying to drop tables:

```bash
# Stop ALL services
docker-compose down

# Start only the database
docker-compose up -d db

# Wait for DB to be ready
sleep 5

# Now drop the schema
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO crm_user; GRANT ALL ON SCHEMA public TO public;"

# Start all services
docker-compose up -d
```

### "Cannot connect to database"

```bash
# Check if database container is running
docker-compose ps db

# Check database logs
docker-compose logs db --tail=50

# Restart database
docker-compose restart db
```

### Migration files not deleted

If migration files persist:

```bash
# Try with more explicit path
docker-compose exec backend bash -c "cd /app && find . -path '*/migrations/0*.py' -delete"

# Or manually delete from each app
docker-compose exec backend bash -c "rm -f /app/conversations/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/customer_data/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/flows/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/football_data_app/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/media_manager/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/meta_integration/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/paynow_integration/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/referrals/migrations/0*.py"
docker-compose exec backend bash -c "rm -f /app/stats/migrations/0*.py"
```

### "No changes detected" when creating migrations

```bash
# Check if __init__.py files exist in migrations directories
docker-compose exec backend bash -c "find /app -path '*/migrations/__init__.py'"

# If missing, create them
docker-compose exec backend bash -c "
for dir in /app/*/migrations/; do
    if [ ! -f \"\$dir/__init__.py\" ]; then
        touch \"\$dir/__init__.py\"
    fi
done
"

# Try makemigrations again
docker-compose exec backend python manage.py makemigrations
```

### Migrations fail to apply

```bash
# Check for model errors
docker-compose exec backend python manage.py check

# Try faking the initial migration (only if you know what you're doing)
docker-compose exec backend python manage.py migrate --fake-initial

# Check database connection
docker-compose exec backend python manage.py dbshell
```

## Restoring from Backup

If something goes wrong and you need to restore:

```bash
# Stop all services
docker-compose down

# Start only the database
docker-compose up -d db

# Wait for DB to be ready
sleep 5

# Drop and recreate the database
docker-compose exec db psql -U crm_user -d postgres -c "DROP DATABASE IF EXISTS whatsapp_crm_dev;"
docker-compose exec db psql -U crm_user -d postgres -c "CREATE DATABASE whatsapp_crm_dev;"

# Restore from backup (replace with your actual backup filename)
cat backup_YYYYMMDD_HHMMSS.sql | docker-compose exec -T db psql -U crm_user -d whatsapp_crm_dev

# Start all services
docker-compose up -d
```

## Useful Database Commands

### View all tables
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "\dt"
```

### View table structure
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "\d tablename"
```

### Count rows in a table
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "SELECT COUNT(*) FROM tablename;"
```

### Drop specific table
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "DROP TABLE IF EXISTS tablename CASCADE;"
```

### Check database size
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev -c "SELECT pg_size_pretty(pg_database_size('whatsapp_crm_dev'));"
```

### List all databases
```bash
docker-compose exec db psql -U crm_user -d postgres -c "\l"
```

## Container Management Commands

### View running containers
```bash
docker-compose ps
```

### View container logs
```bash
# All logs
docker-compose logs

# Specific service
docker-compose logs backend

# Follow logs (live)
docker-compose logs -f backend

# Last N lines
docker-compose logs --tail=100 backend
```

### Restart specific service
```bash
docker-compose restart backend
```

### Stop all services
```bash
docker-compose stop
```

### Start all services
```bash
docker-compose start
```

### Rebuild and restart
```bash
docker-compose up -d --build
```

### Access container shell
```bash
docker-compose exec backend bash
```

### Access Django shell
```bash
docker-compose exec backend python manage.py shell
```

### Access PostgreSQL shell
```bash
docker-compose exec db psql -U crm_user -d whatsapp_crm_dev
```

## Best Practices

1. **Always backup first** - Cannot be stressed enough!
2. **Test in development** - Never run these commands in production without testing
3. **Document your process** - Keep notes of what you did
4. **Use version control** - Commit working migrations before changes
5. **Verify each step** - Check the output of each command before proceeding
6. **Have a rollback plan** - Know how to restore from backup
7. **Communicate with team** - Ensure no one else is working on the database
8. **Check dependencies** - Ensure no external systems are connected to the database

## Related Documentation

- [MIGRATION_RESET_GUIDE.md](MIGRATION_RESET_GUIDE.md) - Comprehensive guide for the Python reset script
- [README.md](README.md) - Project overview and setup
- [GETTING_STARTED.md](GETTING_STARTED.md) - Initial setup guide
- [Django Migrations Documentation](https://docs.djangoproject.com/en/stable/topics/migrations/)
- [PostgreSQL Backup Documentation](https://www.postgresql.org/docs/current/backup.html)

## Support

If you encounter issues not covered in this guide:
1. Check the troubleshooting section
2. Review container logs: `docker-compose logs`
3. Check the project's GitHub issues
4. Consult the Django and PostgreSQL documentation
