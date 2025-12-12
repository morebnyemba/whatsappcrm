# Django Migration Issue Fix: Stale __pycache__ Files

## Problem Description

When running `docker-compose up` or deploying the application, migrations were failing with the error:

```
django.db.utils.ProgrammingError: column "app_secret" of relation "meta_integration_metaappconfig" already exists
```

Even though migration `0003_add_app_secret_field.py` was designed to be idempotent (checking if the column exists before adding it), the error persisted.

## Root Cause

The issue was caused by **stale Python bytecode files** (`.pyc` files) in the `migrations/__pycache__/` directories that were committed to version control.

### How This Happened

1. A migration file was created (e.g., `0002_rename_..._.py`)
2. Python compiled it to bytecode (`0002_rename_..._.pyc`)
3. The `.pyc` file was accidentally committed to git
4. Later, the migration file was replaced with a different one (`0002_placeholder.py`)
5. The old `.py` file was deleted, but the `.pyc` file remained in git
6. When Docker containers started, Python loaded the cached `.pyc` files instead of the actual `.py` files
7. This caused inconsistencies between the migration files and what Django thought needed to be applied

### Why It's a Problem

Python prioritizes `.pyc` files over `.py` files when both exist. When outdated `.pyc` files are present:
- Django's migration system has an inconsistent view of the migration history
- Migrations may try to apply operations that have already been applied
- Or migrations may skip operations that need to be applied
- The migration sequence becomes unpredictable and unreliable

## Solution

### 1. Remove __pycache__ Files from Version Control

All `migrations/__pycache__/` directories and `.pyc` files were removed from git tracking:

```bash
git rm -r --cached **/migrations/__pycache__/
```

This ensures Python will always use the actual `.py` migration files, not cached bytecode.

### 2. Verify .gitignore

The `.gitignore` file already includes these patterns to prevent future issues:

```
__pycache__/
*.py[cod]
**/migrations/__pycache__/
```

### 3. Clean Local Development Environments

If you encounter migration issues locally, clean your `__pycache__` directories:

```bash
# From the project root
find . -type d -name "__pycache__" -path "*/migrations/*" -exec rm -rf {} + 2>/dev/null
```

Or in Docker:

```bash
docker-compose down
docker-compose build --no-cache backend
docker-compose up
```

## Prevention

### For Developers

1. **Never commit `__pycache__` directories**
   - The `.gitignore` file now prevents this
   - Always verify with `git status` before committing

2. **When modifying migrations:**
   - If you need to replace a migration, delete both the `.py` and `.pyc` files
   - Clear local `__pycache__` directories after migration changes
   - Test migrations in a clean environment

3. **Use proper Git practices:**
   ```bash
   # Always check what you're committing
   git status
   git diff --cached
   
   # If you accidentally stage __pycache__ files
   git reset HEAD **/migrations/__pycache__/
   ```

### For Deployment

1. **Docker builds automatically exclude `__pycache__`**
   - Python generates fresh `.pyc` files at runtime
   - No need to include them in the image

2. **CI/CD pipelines should:**
   - Run migrations in a clean environment
   - Never cache migration bytecode between runs
   - Use `--no-cache` flag for Docker builds when migration issues occur

## Migration Best Practices

### Writing Idempotent Migrations

If you need to add a field that might already exist (like the `app_secret` field), use `RunPython` with checks:

```python
def add_field_if_not_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name=%s AND column_name=%s AND table_schema=CURRENT_SCHEMA()
        """, ['table_name', 'column_name'])
        
        if cursor.fetchone() is None:
            cursor.execute("""
                ALTER TABLE table_name 
                ADD COLUMN column_name VARCHAR(255) NULL
            """)

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(add_field_if_not_exists),
    ]
```

### Migration Checklist

Before committing migrations:

- [ ] Test the migration in a fresh database
- [ ] Test the migration against an existing database with data
- [ ] Test the reverse migration
- [ ] Verify no `.pyc` files are being committed
- [ ] Document any manual steps required
- [ ] Test in a staging environment before production

## Troubleshooting

### If you still see migration errors:

1. **Check for stale .pyc files:**
   ```bash
   find . -name "*.pyc" -path "*/migrations/*"
   ```

2. **Clear all Python cache:**
   ```bash
   find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
   find . -name "*.pyc" -delete
   ```

3. **Rebuild Docker containers:**
   ```bash
   docker-compose down -v  # Remove volumes too if needed
   docker-compose build --no-cache
   docker-compose up
   ```

4. **Check migration history in database:**
   ```bash
   docker-compose exec backend python manage.py showmigrations
   ```

5. **Fake a migration if necessary** (use with caution):
   ```bash
   # If the migration has been applied but not recorded
   docker-compose exec backend python manage.py migrate --fake meta_integration 0003
   ```

## Related Files

- `whatsappcrm_backend/meta_integration/migrations/0003_add_app_secret_field.py` - The idempotent migration
- `whatsappcrm_backend/entrypoint.sh` - Runs migrations on container startup
- `.gitignore` - Excludes `__pycache__` directories

## Verification

After this fix is deployed, verify:

1. ✅ No `.pyc` files in the git repository
2. ✅ Migrations run successfully on fresh databases
3. ✅ Migrations run successfully on existing databases
4. ✅ Docker containers start without migration errors
5. ✅ CI/CD pipelines pass

## References

- [Django Migrations Documentation](https://docs.djangoproject.com/en/stable/topics/migrations/)
- [Python Bytecode Cache](https://peps.python.org/pep-3147/)
- [Git Best Practices](https://git-scm.com/doc)
