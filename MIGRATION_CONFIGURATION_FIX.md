# Django Migration Configuration Fix

## Issue Description
The Django application was experiencing migration graph errors when attempting to run migrations:
```
[n.raise_error() for n in self.node_map.values() if isinstance(n, DummyNode)]
File "/usr/local/lib/python3.10/site-packages/django/db/migrations/graph.py", line 198
```

This error typically indicates issues with the migration dependency graph, where migrations reference other migrations that don't exist or create circular dependencies.

## Root Causes Identified

### 1. Incorrect Migration Dependencies
The `customer_data/migrations/0001_initial.py` migration had an incorrect dependency:
- **Before**: Depended on `('conversations', '0006_contact_flow_execution_disabled')`
- **Issue**: An "initial" migration should only depend on other "initial" migrations, not later migrations in the chain
- **After**: Changed to depend on `('conversations', '0001_initial')`

The CustomerProfile model in customer_data only needs a ForeignKey to the Contact model, which is created in conversations' 0001_initial migration. There was no need to depend on migration 0006.

### 2. Environment Configuration for Local Development
The `.env` files contained Docker container hostnames that don't work for local development:
- **DB_HOST='db'** - This is a Docker Compose service name
- **CELERY_BROKER_URL='redis://:mindwell@redis:6379/0'** - Redis container name

These were changed to:
- **DB_HOST='localhost'** - For local PostgreSQL access
- **CELERY_BROKER_URL='redis://:mindwell@localhost:6379/0'** - For local Redis access

## Changes Made

### File: `whatsappcrm_backend/customer_data/migrations/0001_initial.py`
```python
# Before:
dependencies = [
    ('conversations', '0006_contact_flow_execution_disabled'),
    ('football_data_app', '0001_initial'),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
]

# After:
dependencies = [
    ('conversations', '0001_initial'),
    ('football_data_app', '0001_initial'),
    migrations.swappable_dependency(settings.AUTH_USER_MODEL),
]
```

### File: `whatsappcrm_backend/.env`
Updated for local development:
- `DB_HOST='localhost'` (was 'db')
- `CELERY_BROKER_URL='redis://:mindwell@localhost:6379/0'` (was 'redis:6379')

### File: `.env` (root)
Added clarifying comments to distinguish between Docker and local development configurations.

## Verification
The fix was verified by testing the migration graph build:
```python
from django.db.migrations.loader import MigrationLoader
loader = MigrationLoader(None, load=True, ignore_no_migrations=True)
graph = loader.graph
```

**Results:**
- ✓ Migration graph built successfully!
- ✓ Found 88 migrations
- ✓ No missing migration dependencies
- ✓ No DummyNode errors

## Usage Guidelines

### For Docker Deployment
Use the root `.env` file which maintains Docker service names:
```bash
DB_HOST='db'
CELERY_BROKER_URL='redis://:mindwell@redis:6379/0'
```

### For Local Development
Use the `whatsappcrm_backend/.env` file which uses localhost:
```bash
DB_HOST='localhost'
CELERY_BROKER_URL='redis://:mindwell@localhost:6379/0'
```

Ensure you have PostgreSQL and Redis running locally:
```bash
# Start PostgreSQL (example)
sudo systemctl start postgresql

# Start Redis (example)
redis-server
```

## Impact
This fix resolves:
1. Django migration graph errors (DummyNode issues)
2. Database connection errors when running Django management commands locally
3. Confusion between Docker and local development configurations

## Best Practices for Future Migrations
1. **Initial migrations should only depend on other initial migrations** - Don't reference later migrations in the dependency chain
2. **Keep environment-specific settings separate** - Use different .env files for Docker vs local development
3. **Document configuration requirements** - Clearly indicate which settings are for which environment
4. **Test migrations independently** - Always verify the migration graph builds correctly without database access

## Related Documentation
- [Django Migrations Documentation](https://docs.djangoproject.com/en/5.1/topics/migrations/)
- [Migration Graph Debugging](https://docs.djangoproject.com/en/5.1/topics/migrations/#migration-files)
- See also: `MIGRATION_GUIDE.md`, `MIGRATION_RESET_GUIDE.md` in the project root
