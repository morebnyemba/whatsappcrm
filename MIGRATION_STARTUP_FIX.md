# Migration Startup Issue Fix - Quick Guide

## Issue Summary

**Problem:** Application fails to start with a traceback at `manage.py` line 22, showing:
```
ImportError: Couldn't import Django. Are you sure it's installed...
```
or migration-related import errors after the football data tasks load.

**Root Cause:** Stale Python bytecode files (`__pycache__`) in migrations directories causing import errors when Django tries to load migrations during startup.

## Solution Implemented (2026-01-10)

The `entrypoint.sh` script now automatically cleans migration cache on every container startup. This fix is **automatic** and requires no manual intervention.

## How to Apply the Fix

### For Docker Users (Recommended)

1. **Pull the latest changes:**
   ```bash
   git pull origin copilot/update-football-data-provider
   ```

2. **Rebuild and restart containers:**
   ```bash
   docker-compose down
   docker-compose build --no-cache backend
   docker-compose up -d
   ```

3. **Verify the fix is working:**
   ```bash
   docker-compose logs backend | grep "Cleaning up migration"
   ```
   
   You should see:
   ```
   Cleaning up migration __pycache__ directories...
   Migration cache cleanup complete.
   ```

### For Local Development (Without Docker)

If you're running the application locally without Docker and encounter migration issues:

1. **Clean migration cache manually:**
   ```bash
   cd whatsappcrm_backend
   find . -type d -name "__pycache__" -path "*/migrations/*" -exec rm -rf {} + 2>/dev/null
   ```

2. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

## What This Fix Does

- **Automatically cleans** migration `__pycache__` directories on container startup
- **Prevents** stale bytecode from causing import errors
- **Works for all services:** web, celeryworker, celerybeat
- **Safe to run repeatedly** with no side effects

## Verification Steps

After applying the fix, verify that:

1. ✅ Container starts successfully without errors
2. ✅ Migrations run without import errors
3. ✅ Application logs show the cleanup message
4. ✅ Django admin is accessible

## Troubleshooting

### If containers still fail to start:

1. **Check for other errors in logs:**
   ```bash
   docker-compose logs backend
   ```

2. **Ensure dependencies are installed:**
   ```bash
   docker-compose exec backend pip list | grep -i django
   ```

3. **Check database connection:**
   ```bash
   docker-compose exec backend python manage.py check --database default
   ```

4. **Verify .env file:**
   - Ensure `DB_HOST=db`
   - Ensure `REDIS_PASSWORD` is set
   - Ensure `CELERY_BROKER_URL` includes the Redis password

### Common Issues

**Database connection errors:**
- Wait for the database to be ready: `docker-compose logs db`
- Check that the `db` service is healthy: `docker-compose ps`

**Redis connection errors:**
- Verify Redis is running: `docker-compose logs redis`
- Check `REDIS_PASSWORD` in `.env` matches the Redis password

**Module import errors:**
- Rebuild containers: `docker-compose build --no-cache`
- Check Python version: `docker-compose exec backend python --version` (should be 3.10)

## Related Documentation

- [MIGRATION_PYCACHE_FIX.md](./MIGRATION_PYCACHE_FIX.md) - Detailed explanation and history
- [GETTING_STARTED.md](./GETTING_STARTED.md) - General setup guide
- [MIGRATION_RESET_GUIDE.md](./MIGRATION_RESET_GUIDE.md) - How to reset migrations if needed

## Support

If you continue to experience issues after applying this fix:

1. Check the [MIGRATION_PYCACHE_FIX.md](./MIGRATION_PYCACHE_FIX.md) for detailed troubleshooting
2. Review the entrypoint logs: `docker-compose logs backend | head -50`
3. Verify the fix was applied: `git log --oneline | head -5`

## Technical Details

**What changed:**
- Modified `whatsappcrm_backend/entrypoint.sh` to include automatic cleanup
- Cleaned existing `__pycache__` directories from the repository

**Why this works:**
- Docker volume mounts can bring stale `__pycache__` from host to container
- Python prioritizes `.pyc` files over `.py` files
- Cleaning before startup ensures Python always uses current `.py` files

**Safety:**
- The cleanup only removes compiled bytecode, not source files
- Python automatically regenerates `.pyc` files as needed
- No data or migration files are affected
