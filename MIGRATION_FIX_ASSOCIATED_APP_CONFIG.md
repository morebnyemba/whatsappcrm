# Fix for Missing associated_app_config Column

## Problem
The application was experiencing a `ProgrammingError` in the Celery task `cleanup_idle_conversations_task`:

```
django.db.utils.ProgrammingError: column conversations_contact.associated_app_config_id does not exist
```

## Root Cause
The `Contact` model in `conversations/models.py` had an `associated_app_config` ForeignKey field defined (lines 28-35), but there was no corresponding database migration to create this column in the database.

## Solution
A new migration file has been created: `whatsappcrm_backend/conversations/migrations/0007_contact_associated_app_config.py`

This migration adds the missing `associated_app_config` field to the `Contact` model as a ForeignKey to `meta_integration.MetaAppConfig`.

## How to Apply the Fix

### Option 1: Using Docker Compose (Recommended for Production)

1. Stop the running containers:
   ```bash
   docker-compose down
   ```

2. Apply the migration:
   ```bash
   docker-compose run --rm backend python manage.py migrate conversations
   ```

3. Restart the services:
   ```bash
   docker-compose up -d
   ```

### Option 2: Running Migration on the Backend Container

If your containers are already running:

```bash
docker-compose exec backend python manage.py migrate conversations
```

### Option 3: Direct Database Access (Not Recommended)

If you prefer to apply the migration manually via SQL (only for emergencies):

```sql
ALTER TABLE conversations_contact 
ADD COLUMN associated_app_config_id BIGINT NULL 
REFERENCES meta_integration_metaappconfig(id) 
ON DELETE SET NULL;

CREATE INDEX conversations_contact_associated_app_config_id_idx 
ON conversations_contact(associated_app_config_id);
```

## Verification

After applying the migration, verify it worked:

```bash
# Check migration status
docker-compose exec backend python manage.py showmigrations conversations

# You should see:
# [X] 0007_contact_associated_app_config
```

## Expected Behavior After Fix

1. The Celery task `cleanup_idle_conversations_task` should run without errors
2. Contacts can now be associated with specific Meta App Configurations
3. The system can handle multiple WhatsApp business numbers through different configurations

## Notes

- This is a nullable field (`null=True, blank=True`), so existing contacts will have `NULL` for this field
- The field uses `on_delete=models.SET_NULL` to preserve contacts even if the associated configuration is deleted
- The migration has a dependency on `meta_integration` migration `0004_webhookeventlog_message`
