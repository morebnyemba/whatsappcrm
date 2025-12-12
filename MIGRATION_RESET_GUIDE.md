# Migration Reset Script - Usage Guide

This document explains how to use the `reset_migrations.py` script to fix migration errors in the WhatsApp CRM project.

## Purpose

The `reset_migrations.py` script is designed to resolve migration conflicts and errors by:
1. Dropping all tables from the PostgreSQL database
2. Deleting all existing migration files (except `__init__.py`)
3. Creating fresh migrations for all Django apps
4. Applying the new migrations to rebuild the database schema

## ⚠️ WARNING

**This script is DESTRUCTIVE and will DELETE ALL DATA in your database!**

- Use this script only when you have migration conflicts that cannot be resolved through normal means
- Always backup your database before running this script
- Only run this in development environments unless you're absolutely certain
- All existing data will be lost and cannot be recovered without a backup

## Prerequisites

Before running the script, ensure:

1. **Python dependencies are installed**:
   ```bash
   cd whatsappcrm_backend
   pip install -r requirements.txt
   ```

2. **Database credentials are configured in `.env`**:
   The script reads database credentials from the project's root `.env` file. Ensure the following variables are set:
   ```env
   DB_ENGINE=django.db.backends.postgresql
   DB_NAME=whatsapp_crm_dev
   DB_USER=crm_user
   DB_PASSWORD=your_password_here
   DB_HOST=localhost  # or 'db' for Docker
   DB_PORT=5432
   ```

3. **PostgreSQL is running**:
   - If using Docker: `docker-compose up -d db`
   - If using local PostgreSQL: Ensure the service is running

4. **Database exists**:
   The database specified in `DB_NAME` must already exist. If not, create it:
   ```bash
   # For local PostgreSQL
   createdb -U crm_user whatsapp_crm_dev
   
   # For Docker
   docker-compose exec db psql -U crm_user -c "CREATE DATABASE whatsapp_crm_dev;"
   ```

## Usage

### Quick Start (Recommended)

The easiest way to run the script is using the provided shell script wrapper:

```bash
./reset_migrations.sh
```

This script will:
- Auto-detect if you're using Docker or a local environment
- Handle environment-specific setup
- Execute the migration reset process

### Manual Usage

Alternatively, you can run the Python script directly:

```bash
python reset_migrations.py
```

### Step-by-Step Process

1. **Navigate to the project root**:
   ```bash
   cd /path/to/whatsappcrm
   ```

2. **Verify your .env file has correct database credentials**:
   ```bash
   cat .env | grep DB_
   ```

3. **Run the script**:
   ```bash
   python reset_migrations.py
   ```

4. **Confirm the operation**:
   The script will display a warning and ask for confirmation. Type `YES` (all caps) to proceed.

5. **Follow the prompts**:
   - The script will drop all tables
   - Delete migration files
   - Create new migrations
   - Apply migrations
   - Optionally, create a superuser account

### Docker Environment

If you're using Docker, the shell script wrapper (`reset_migrations.sh`) automatically handles Docker environments.

#### Using the Shell Script (Recommended)

```bash
./reset_migrations.sh
```

The script will:
1. Detect that you're using Docker
2. Start the backend container if it's not running
3. Copy the Python script to the container
4. Execute it inside the container
5. Clean up temporary files

#### Manual Docker Execution

If you prefer to run the Python script directly:

**Option 1: Execute from host machine**

Ensure your `.env` has `DB_HOST=localhost` and the database port is exposed:

```bash
python reset_migrations.py
```

**Option 2: Execute inside Docker container**

```bash
# Start the backend container
docker-compose up -d backend

# Run the script inside the container
docker-compose exec backend python reset_migrations.py
```

Note: The script reads from the `.env` file in the project root, which is mounted into the container. When running inside Docker, ensure `DB_HOST=db` in your `.env`.

## What the Script Does

### 1. Load Environment Variables
Reads database credentials from the root `.env` file:
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`

### 2. Drop All Tables
Connects to PostgreSQL and executes:
```sql
DROP TABLE IF EXISTS <table_name> CASCADE;
```
for every table in the `public` schema.

### 3. Delete Migration Files
Removes all migration files from these apps:
- `football_data_app`
- `meta_integration`
- `media_manager`
- `referrals`
- `customer_data`
- `flows`
- `stats`
- `conversations`
- `paynow_integration`

The `__init__.py` files are preserved to maintain Python package structure.

### 4. Create New Migrations
Runs:
```bash
python manage.py makemigrations
```

This creates fresh migration files based on the current model definitions.

### 5. Apply Migrations
Runs:
```bash
python manage.py migrate
```

This applies all migrations to create the database schema.

### 6. Create Superuser (Optional)
Prompts you to create a Django superuser account for admin access.

## Troubleshooting

### Script cannot find .env file

**Error**: `.env file not found`

**Solution**: Ensure you're running the script from the project root directory where the `.env` file is located.

### Database connection failed

**Error**: `Failed to connect to database`

**Possible causes**:
1. PostgreSQL is not running
2. Wrong credentials in `.env`
3. Database host is incorrect (use `localhost` for local, `db` for Docker)
4. Database port is not accessible

**Solution**:
```bash
# Check if PostgreSQL is running
# For Docker:
docker-compose ps db

# For local:
sudo systemctl status postgresql

# Test connection manually
psql -h localhost -U crm_user -d whatsapp_crm_dev
```

### Django import error

**Error**: `ModuleNotFoundError: No module named 'django'`

**Solution**: Install Python dependencies:
```bash
cd whatsappcrm_backend
pip install -r requirements.txt
```

### Migration creation fails

**Error**: Errors during `makemigrations` step

**Possible causes**:
1. Model definition errors in your code
2. Missing dependencies
3. Import errors

**Solution**:
1. Check the error message for specific model issues
2. Fix model definitions in your apps
3. Ensure all dependencies are installed

### Migration application fails

**Error**: Errors during `migrate` step

**Possible causes**:
1. Database constraint violations
2. Missing dependencies between migrations
3. Incompatible migrations

**Solution**:
1. Review the error message
2. Check for circular dependencies in models
3. Ensure Foreign Keys reference existing models

## After Running the Script

Once the script completes successfully:

1. **Verify the database schema**:
   ```bash
   python manage.py dbshell
   \dt  # List all tables
   \q   # Exit
   ```

2. **Create a superuser** (if you skipped it during the script):
   ```bash
   cd whatsappcrm_backend
   python manage.py createsuperuser
   ```

3. **Load initial data** (if you have fixtures):
   ```bash
   python manage.py loaddata initial_data.json
   ```

4. **Run the development server**:
   ```bash
   python manage.py runserver
   ```

5. **Access Django admin**:
   Visit `http://localhost:8000/admin` and log in with your superuser account.

## Best Practices

1. **Always backup before running**:
   ```bash
   # Backup database
   pg_dump -U crm_user -h localhost whatsapp_crm_dev > backup_$(date +%Y%m%d_%H%M%S).sql
   ```

2. **Test in development first**: Never run this on production without testing.

3. **Document your changes**: Keep track of what data needs to be restored.

4. **Use version control**: Commit working migration files before making changes.

5. **Consider alternatives**: Before using this script, try:
   - `python manage.py migrate --fake-initial`
   - `python manage.py migrate --fake <app> zero`
   - Manually resolving migration conflicts

## Restoring from Backup

If you need to restore from a backup after running the script:

```bash
# Drop the database
dropdb -U crm_user whatsapp_crm_dev

# Recreate it
createdb -U crm_user whatsapp_crm_dev

# Restore from backup
psql -U crm_user -h localhost -d whatsapp_crm_dev < backup_20231212_120000.sql
```

## Support

If you encounter issues:

1. Check the logs output by the script
2. Review Django and PostgreSQL logs
3. Consult Django migration documentation
4. Check the project's GitHub issues

## Related Documentation

- [Django Migrations Documentation](https://docs.djangoproject.com/en/stable/topics/migrations/)
- [PostgreSQL Backup and Restore](https://www.postgresql.org/docs/current/backup.html)
- [Project Migration Guide](./MIGRATION_GUIDE.md)
