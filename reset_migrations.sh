#!/bin/bash
#
# Migration Reset Script Wrapper
# This script provides a convenient way to run the migration reset script
# in both local and Docker environments.
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
echo -e "${BLUE}WhatsApp CRM - Migration Reset Script${NC}"
echo -e "${BLUE}================================================${NC}\n"

# Check if .env file exists
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo -e "${RED}❌ Error: .env file not found in ${SCRIPT_DIR}${NC}"
    echo -e "${YELLOW}Please create a .env file with database credentials.${NC}"
    exit 1
fi

# Determine environment (Docker or local)
echo -e "${BLUE}Detecting environment...${NC}"

if command -v docker-compose &> /dev/null && docker-compose ps | grep -q "whatsappcrm_backend_app"; then
    echo -e "${GREEN}✅ Docker environment detected${NC}\n"
    ENVIRONMENT="docker"
elif command -v python3 &> /dev/null; then
    echo -e "${GREEN}✅ Local Python environment detected${NC}\n"
    ENVIRONMENT="local"
else
    echo -e "${RED}❌ Error: Could not detect a suitable environment${NC}"
    echo -e "${YELLOW}Please ensure either Docker is running or Python 3 is installed.${NC}"
    exit 1
fi

# Display warning
echo -e "${RED}⚠️  WARNING: DESTRUCTIVE OPERATION ⚠️${NC}"
echo -e "${YELLOW}This script will DELETE ALL DATA in your database!${NC}\n"

# Prompt for confirmation
read -p "Do you want to continue? (Type 'yes' to proceed): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo -e "${YELLOW}Operation cancelled.${NC}"
    exit 0
fi

echo ""

# Run the script based on environment
if [ "$ENVIRONMENT" = "docker" ]; then
    echo -e "${BLUE}Running migration reset in Docker container...${NC}\n"
    
    # Check if backend container is running
    if ! docker-compose ps | grep -q "whatsappcrm_backend_app.*Up"; then
        echo -e "${YELLOW}Backend container is not running. Starting it...${NC}"
        docker-compose up -d backend
        echo -e "${GREEN}Waiting for backend to be ready...${NC}"
        sleep 5
    fi
    
    # Copy script to container and execute
    docker cp "${SCRIPT_DIR}/reset_migrations.py" whatsappcrm_backend_app:/tmp/reset_migrations.py
    docker-compose exec backend python /tmp/reset_migrations.py
    
    # Clean up
    docker-compose exec backend rm /tmp/reset_migrations.py
    
else
    echo -e "${BLUE}Running migration reset locally...${NC}\n"
    
    # Check if Python dependencies are installed
    if ! python3 -c "import django" 2>/dev/null; then
        echo -e "${YELLOW}⚠️  Django not found. Installing dependencies...${NC}"
        pip3 install -r "${SCRIPT_DIR}/whatsappcrm_backend/requirements.txt"
    fi
    
    # Run the script
    python3 "${SCRIPT_DIR}/reset_migrations.py"
fi

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}Migration reset process completed!${NC}"
echo -e "${GREEN}================================================${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo -e "  1. Verify the database structure"
echo -e "  2. Create a superuser if needed"
echo -e "  3. Load initial data fixtures"
echo -e "  4. Restart your application\n"
