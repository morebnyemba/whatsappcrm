# Generated manually for adding message field to WebhookEventLog

from django.db import migrations, models
import django.db.models.deletion


def add_message_field_if_not_exists(apps, schema_editor):
    """
    Add message field to WebhookEventLog if it doesn't already exist.
    This makes the migration idempotent and handles cases where the column
    may have already been added through other means.
    """
    # Check if the column already exists
    with schema_editor.connection.cursor() as cursor:
        table_name = 'meta_integration_webhookeventlog'
        
        # Check if the column exists (PostgreSQL specific query)
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name=%s AND column_name=%s
        """, [table_name, 'message_id'])
        
        column_exists = cursor.fetchone() is not None
    
    # Only add the field if it doesn't exist
    if not column_exists:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE meta_integration_webhookeventlog 
                ADD COLUMN message_id BIGINT NULL 
                CONSTRAINT meta_integration_webhookeventlog_message_id_fk 
                REFERENCES conversations_message(id) 
                ON DELETE SET NULL
            """)


def reverse_add_message_field(apps, schema_editor):
    """
    Remove message field from WebhookEventLog if it exists.
    """
    with schema_editor.connection.cursor() as cursor:
        table_name = 'meta_integration_webhookeventlog'
        
        # Check if the column exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name=%s AND column_name=%s
        """, [table_name, 'message_id'])
        
        column_exists = cursor.fetchone() is not None
    
    # Only drop the field if it exists
    if column_exists:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE meta_integration_webhookeventlog 
                DROP COLUMN message_id
            """)


class Migration(migrations.Migration):

    dependencies = [
        ('conversations', '0001_initial'),
        ('meta_integration', '0003_add_app_secret_field'),
    ]

    operations = [
        migrations.RunPython(
            add_message_field_if_not_exists,
            reverse_code=reverse_add_message_field,
        ),
    ]
