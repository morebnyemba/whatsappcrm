# Generated manually for adding app_secret field

from django.db import migrations, models


def check_and_add_app_secret_field(apps, schema_editor):
    """
    Add app_secret field to MetaAppConfig if it doesn't already exist.
    This makes the migration idempotent and handles cases where the column
    may have already been added through other means.
    """
    # Check if the column already exists
    with schema_editor.connection.cursor() as cursor:
        # Get the table name for the model
        table_name = 'meta_integration_metaappconfig'
        
        # Check if the column exists (PostgreSQL specific query)
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name=%s AND column_name=%s AND table_schema=CURRENT_SCHEMA()
        """, [table_name, 'app_secret'])
        
        column_exists = cursor.fetchone() is not None
    
    # Only add the field if it doesn't exist
    if not column_exists:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE meta_integration_metaappconfig 
                ADD COLUMN app_secret VARCHAR(255) NULL
            """)


def reverse_app_secret_field(apps, schema_editor):
    """
    Remove app_secret field from MetaAppConfig if it exists.
    """
    with schema_editor.connection.cursor() as cursor:
        table_name = 'meta_integration_metaappconfig'
        
        # Check if the column exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name=%s AND column_name=%s AND table_schema=CURRENT_SCHEMA()
        """, [table_name, 'app_secret'])
        
        column_exists = cursor.fetchone() is not None
    
    # Only drop the field if it exists
    if column_exists:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("""
                ALTER TABLE meta_integration_metaappconfig 
                DROP COLUMN app_secret
            """)


class Migration(migrations.Migration):

    dependencies = [
        ('meta_integration', '0002_placeholder'),
    ]

    operations = [
        # Use SeparateDatabaseAndState to ensure Django's migration state is updated
        # while still allowing idempotent database operations
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    check_and_add_app_secret_field,
                    reverse_code=reverse_app_secret_field,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='metaappconfig',
                    name='app_secret',
                    field=models.CharField(
                        blank=True,
                        help_text='The App Secret from the Meta App Dashboard, used for verifying webhook signature. Recommended for security.',
                        max_length=255,
                        null=True
                    ),
                ),
            ],
        ),
    ]
