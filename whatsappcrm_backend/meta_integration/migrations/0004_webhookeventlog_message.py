# Generated manually for adding message field to WebhookEventLog

from django.db import migrations, models
import django.db.models.deletion


def check_and_add_message_field(apps, schema_editor):
    """
    Add message field to WebhookEventLog if it doesn't already exist.
    This makes the migration idempotent and handles cases where the column
    may have already been added through other means.
    """
    # Check if the column already exists
    table_name = 'meta_integration_webhookeventlog'
    column_exists = False
    
    with schema_editor.connection.cursor() as cursor:
        db_vendor = schema_editor.connection.vendor
        
        if db_vendor == 'postgresql':
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name=%s AND column_name=%s AND table_schema=CURRENT_SCHEMA()
            """, [table_name, 'message_id'])
            column_exists = cursor.fetchone() is not None
        elif db_vendor == 'sqlite':
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            column_exists = 'message_id' in columns
        elif db_vendor == 'mysql':
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME=%s AND COLUMN_NAME=%s AND TABLE_SCHEMA=DATABASE()
            """, [table_name, 'message_id'])
            column_exists = cursor.fetchone() is not None
    
    # Only add the field if it doesn't exist
    if not column_exists:
        with schema_editor.connection.cursor() as cursor:
            db_vendor = schema_editor.connection.vendor
            # Add column first
            if db_vendor == 'sqlite':
                cursor.execute(f"""
                    ALTER TABLE {table_name} 
                    ADD COLUMN message_id BIGINT NULL
                """)
            else:
                cursor.execute("""
                    ALTER TABLE meta_integration_webhookeventlog 
                    ADD COLUMN message_id BIGINT NULL
                """)
            # Then add foreign key constraint (if not SQLite)
            if db_vendor != 'sqlite':
                cursor.execute("""
                    ALTER TABLE meta_integration_webhookeventlog 
                    ADD CONSTRAINT meta_integration_webhookeventlog_message_id_fk 
                    FOREIGN KEY (message_id) 
                    REFERENCES conversations_message(id) 
                    ON DELETE SET NULL
                """)


def reverse_message_field(apps, schema_editor):
    """
    Remove message field from WebhookEventLog if it exists.
    """
    table_name = 'meta_integration_webhookeventlog'
    column_exists = False
    
    with schema_editor.connection.cursor() as cursor:
        db_vendor = schema_editor.connection.vendor
        
        if db_vendor == 'postgresql':
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name=%s AND column_name=%s AND table_schema=CURRENT_SCHEMA()
            """, [table_name, 'message_id'])
            column_exists = cursor.fetchone() is not None
        elif db_vendor == 'sqlite':
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            column_exists = 'message_id' in columns
        elif db_vendor == 'mysql':
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME=%s AND COLUMN_NAME=%s AND TABLE_SCHEMA=DATABASE()
            """, [table_name, 'message_id'])
            column_exists = cursor.fetchone() is not None
    
    # Only drop the field if it exists
    if column_exists:
        with schema_editor.connection.cursor() as cursor:
            db_vendor = schema_editor.connection.vendor
            # Drop the constraint first (if not SQLite)
            if db_vendor != 'sqlite':
                cursor.execute("""
                    ALTER TABLE meta_integration_webhookeventlog 
                    DROP CONSTRAINT IF EXISTS meta_integration_webhookeventlog_message_id_fk
                """)
            # Then drop the column
            cursor.execute(f"""
                ALTER TABLE {table_name} 
                DROP COLUMN message_id
            """)


class Migration(migrations.Migration):

    dependencies = [
        ('conversations', '0001_initial'),
        ('meta_integration', '0003_add_app_secret_field'),
    ]

    operations = [
        # Use SeparateDatabaseAndState to ensure Django's migration state is updated
        # while still allowing idempotent database operations
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    check_and_add_message_field,
                    reverse_code=reverse_message_field,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='webhookeventlog',
                    name='message',
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to='conversations.message',
                        help_text='Link to the Message object if this event relates to a message.'
                    ),
                ),
            ],
        ),
    ]
