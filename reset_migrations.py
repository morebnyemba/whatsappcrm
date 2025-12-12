#!/usr/bin/env python3
"""
Migration Reset Script for WhatsApp CRM

This script:
1. Reads database credentials from the project's root .env file
2. Connects to PostgreSQL and drops all tables
3. Deletes existing migration files (preserving __init__.py)
4. Creates new migrations for all Django apps
5. Applies the new migrations

Usage:
    python reset_migrations.py

Requirements:
    - psycopg2-binary (for PostgreSQL connection)
    - python-dotenv (for reading .env file)
    - Django and project dependencies
"""

import os
import sys
import subprocess
import psycopg2
from psycopg2 import sql
from pathlib import Path
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get the project root directory (where this script is located)
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "whatsappcrm_backend"

# Load environment variables from root .env file
env_file = PROJECT_ROOT / ".env"
if not env_file.exists():
    logger.error(f"❌ .env file not found at {env_file}")
    sys.exit(1)

logger.info(f"📄 Loading environment variables from {env_file}")
load_dotenv(env_file)

# Get database credentials from .env
DB_NAME = os.getenv('DB_NAME', 'whatsapp_crm_dev')
DB_USER = os.getenv('DB_USER', 'crm_user')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')

# Validate required environment variables
if not DB_PASSWORD:
    logger.error("❌ DB_PASSWORD not found in .env file")
    sys.exit(1)

logger.info(f"📊 Database Configuration:")
logger.info(f"   - Host: {DB_HOST}")
logger.info(f"   - Port: {DB_PORT}")
logger.info(f"   - Database: {DB_NAME}")
logger.info(f"   - User: {DB_USER}")

# List of custom apps that have migrations
# NOTE: This list must be kept in sync with the INSTALLED_APPS in settings.py
# If you add new Django apps to your project, update this list accordingly
CUSTOM_APPS = [
    'football_data_app',
    'meta_integration',
    'media_manager',
    'referrals',
    'customer_data',
    'flows',
    'stats',
    'conversations',
    'paynow_integration',
]


def confirm_action():
    """Ask user to confirm the destructive action."""
    print("\n" + "="*70)
    print("⚠️  WARNING: DESTRUCTIVE OPERATION ⚠️")
    print("="*70)
    print("\nThis script will:")
    print("  1. DROP ALL TABLES from the database")
    print("  2. DELETE all migration files")
    print("  3. CREATE new migrations")
    print("  4. APPLY new migrations")
    print("\n⚠️  ALL DATA IN THE DATABASE WILL BE LOST! ⚠️")
    print("="*70)
    
    response = input("\nType 'YES' to continue or anything else to cancel: ")
    if response.strip() != 'YES':
        logger.info("❌ Operation cancelled by user")
        sys.exit(0)
    
    logger.info("✅ User confirmed the operation")


def connect_to_db():
    """Connect to PostgreSQL database."""
    try:
        logger.info(f"🔌 Connecting to PostgreSQL database '{DB_NAME}'...")
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        conn.autocommit = True
        logger.info("✅ Successfully connected to database")
        return conn
    except psycopg2.Error as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        sys.exit(1)


def drop_all_tables(conn):
    """Drop all tables from the database."""
    try:
        cursor = conn.cursor()
        
        logger.info("🗑️  Fetching list of all tables...")
        # Get all tables in the public schema
        cursor.execute("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public';
        """)
        tables = cursor.fetchall()
        
        if not tables:
            logger.info("ℹ️  No tables found in database")
            return
        
        logger.info(f"📋 Found {len(tables)} tables to drop")
        
        # Drop all tables using parameterized query for security
        for table in tables:
            table_name = table[0]
            logger.info(f"   - Dropping table: {table_name}")
            # Use identifier quoting to safely handle table names
            cursor.execute(
                sql.SQL('DROP TABLE IF EXISTS {} CASCADE;').format(
                    sql.Identifier(table_name)
                )
            )
        
        logger.info("✅ All tables dropped successfully")
        cursor.close()
        
    except psycopg2.Error as e:
        logger.error(f"❌ Failed to drop tables: {e}")
        sys.exit(1)


def delete_migration_files():
    """Delete all migration files except __init__.py."""
    logger.info("🗑️  Deleting migration files...")
    
    deleted_count = 0
    for app in CUSTOM_APPS:
        migrations_dir = BACKEND_DIR / app / "migrations"
        
        if not migrations_dir.exists():
            logger.warning(f"⚠️  Migration directory not found: {migrations_dir}")
            continue
        
        logger.info(f"   - Processing {app}/migrations/")
        
        # Delete all .py files except __init__.py
        for file in migrations_dir.glob("*.py"):
            if file.name != "__init__.py":
                logger.info(f"     • Deleting {file.name}")
                file.unlink()
                deleted_count += 1
        
        # Delete __pycache__ directories
        pycache_dir = migrations_dir / "__pycache__"
        if pycache_dir.exists():
            logger.info(f"     • Deleting __pycache__/")
            for file in pycache_dir.glob("*"):
                file.unlink()
            pycache_dir.rmdir()
        
        # Ensure __init__.py exists
        init_file = migrations_dir / "__init__.py"
        if not init_file.exists():
            logger.info(f"     • Creating __init__.py")
            init_file.touch()
    
    logger.info(f"✅ Deleted {deleted_count} migration files")


def run_django_command(command):
    """Run a Django management command."""
    try:
        # Change to backend directory
        os.chdir(BACKEND_DIR)
        
        # Set environment variable for Django settings
        env = os.environ.copy()
        env['DJANGO_SETTINGS_MODULE'] = 'whatsappcrm_backend.settings'
        
        logger.info(f"🔧 Running: python manage.py {' '.join(command)}")
        
        result = subprocess.run(
            ['python', 'manage.py'] + command,
            env=env,
            capture_output=True,
            text=True,
            check=True
        )
        
        if result.stdout:
            logger.info(result.stdout)
        if result.stderr:
            logger.warning(result.stderr)
            
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Command failed with exit code {e.returncode}")
        if e.stdout:
            logger.error(f"STDOUT: {e.stdout}")
        if e.stderr:
            logger.error(f"STDERR: {e.stderr}")
        return False


def create_migrations():
    """Create new migrations for all apps."""
    logger.info("\n📝 Creating new migrations...")
    
    success = run_django_command(['makemigrations'])
    
    if success:
        logger.info("✅ Migrations created successfully")
        return True
    else:
        logger.error("❌ Failed to create migrations")
        return False


def apply_migrations():
    """Apply all migrations."""
    logger.info("\n📤 Applying migrations...")
    
    success = run_django_command(['migrate'])
    
    if success:
        logger.info("✅ Migrations applied successfully")
        return True
    else:
        logger.error("❌ Failed to apply migrations")
        return False


def create_superuser_prompt():
    """Prompt to create a superuser."""
    logger.info("\n" + "="*70)
    print("\n👤 Would you like to create a superuser now?")
    response = input("Type 'yes' to create a superuser or anything else to skip: ")
    
    if response.strip().lower() == 'yes':
        logger.info("🔧 Creating superuser...")
        run_django_command(['createsuperuser'])
    else:
        logger.info("ℹ️  Skipped superuser creation")


def main():
    """Main execution function."""
    logger.info("\n" + "="*70)
    logger.info("🚀 WhatsApp CRM - Migration Reset Script")
    logger.info("="*70)
    
    # Confirm the operation
    confirm_action()
    
    # Step 1: Connect to database
    logger.info("\n📍 Step 1: Connecting to database...")
    conn = connect_to_db()
    
    # Step 2: Drop all tables
    logger.info("\n📍 Step 2: Dropping all tables...")
    drop_all_tables(conn)
    conn.close()
    
    # Step 3: Delete migration files
    logger.info("\n📍 Step 3: Deleting migration files...")
    delete_migration_files()
    
    # Step 4: Create new migrations
    logger.info("\n📍 Step 4: Creating new migrations...")
    if not create_migrations():
        logger.error("\n❌ Failed to create migrations. Exiting.")
        sys.exit(1)
    
    # Step 5: Apply migrations
    logger.info("\n📍 Step 5: Applying migrations...")
    if not apply_migrations():
        logger.error("\n❌ Failed to apply migrations. Exiting.")
        sys.exit(1)
    
    # Optional: Create superuser
    create_superuser_prompt()
    
    # Success message
    logger.info("\n" + "="*70)
    logger.info("🎉 Migration reset completed successfully!")
    logger.info("="*70)
    logger.info("\nNext steps:")
    logger.info("  1. Verify the database structure")
    logger.info("  2. Load any necessary initial data")
    logger.info("  3. Test the application")
    logger.info("\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n❌ Operation cancelled by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}", exc_info=True)
        sys.exit(1)
