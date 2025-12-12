#!/bin/bash
#
# Database Backup Script
# Creates a backup of the PostgreSQL database before running migration reset
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}WhatsApp CRM - Database Backup Script${NC}"
echo -e "${BLUE}================================================${NC}\n"

# Check if .env file exists
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo -e "${RED}❌ Error: .env file not found in ${SCRIPT_DIR}${NC}"
    exit 1
fi

# Load environment variables
source "${SCRIPT_DIR}/.env"

# Use defaults if not set
DB_NAME="${DB_NAME:-whatsapp_crm_dev}"
DB_USER="${DB_USER:-crm_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

# Generate backup filename with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${SCRIPT_DIR}/backups"
BACKUP_FILE="${BACKUP_DIR}/backup_${DB_NAME}_${TIMESTAMP}.sql"

# Create backups directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

echo -e "${BLUE}Database Configuration:${NC}"
echo -e "  Host: ${DB_HOST}"
echo -e "  Port: ${DB_PORT}"
echo -e "  Database: ${DB_NAME}"
echo -e "  User: ${DB_USER}\n"

# Check if we're using Docker
if command -v docker-compose &> /dev/null && docker-compose ps | grep -q "whatsappcrm_db"; then
    echo -e "${GREEN}Using Docker environment${NC}\n"
    
    echo -e "${YELLOW}Creating database backup...${NC}"
    docker-compose exec -T db pg_dump -U "${DB_USER}" "${DB_NAME}" > "${BACKUP_FILE}"
    
elif command -v docker &> /dev/null && docker compose ps | grep -q "whatsappcrm_db"; then
    echo -e "${GREEN}Using Docker environment (v2)${NC}\n"
    
    echo -e "${YELLOW}Creating database backup...${NC}"
    docker compose exec -T db pg_dump -U "${DB_USER}" "${DB_NAME}" > "${BACKUP_FILE}"
    
else
    echo -e "${GREEN}Using local PostgreSQL${NC}\n"
    
    # Check if pg_dump is available
    if ! command -v pg_dump &> /dev/null; then
        echo -e "${RED}❌ Error: pg_dump not found${NC}"
        echo -e "${YELLOW}Please install PostgreSQL client tools${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}Creating database backup...${NC}"
    PGPASSWORD="${DB_PASSWORD}" pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" "${DB_NAME}" > "${BACKUP_FILE}"
fi

# Check if backup was successful
if [ -f "${BACKUP_FILE}" ] && [ -s "${BACKUP_FILE}" ]; then
    BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo -e "${GREEN}✅ Backup created successfully!${NC}\n"
    echo -e "${BLUE}Backup Details:${NC}"
    echo -e "  File: ${BACKUP_FILE}"
    echo -e "  Size: ${BACKUP_SIZE}\n"
    
    echo -e "${GREEN}To restore this backup later:${NC}"
    if command -v docker-compose &> /dev/null || command -v docker &> /dev/null; then
        echo -e "  ${YELLOW}docker-compose exec -T db psql -U ${DB_USER} ${DB_NAME} < ${BACKUP_FILE}${NC}"
    else
        echo -e "  ${YELLOW}PGPASSWORD=\${DB_PASSWORD} psql -h ${DB_HOST} -p ${DB_PORT} -U ${DB_USER} ${DB_NAME} < ${BACKUP_FILE}${NC}"
    fi
    echo ""
else
    echo -e "${RED}❌ Backup failed or file is empty${NC}"
    exit 1
fi

# List recent backups
echo -e "${BLUE}Recent backups:${NC}"
ls -lht "${BACKUP_DIR}" | head -6
echo ""

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Backup completed successfully!${NC}"
echo -e "${GREEN}================================================${NC}\n"
