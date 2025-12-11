#!/bin/bash
# Celery Worker Verification Script
# This script checks if both Celery workers are running correctly

set -e

echo "=========================================="
echo "Celery Worker Verification Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $2"
    else
        echo -e "${RED}✗${NC} $2"
    fi
}

echo "1. Checking if Docker containers are running..."
echo "================================================"

# Check WhatsApp worker
if docker ps | grep -q "whatsappcrm_celery_worker_whatsapp"; then
    print_status 0 "WhatsApp worker container is running"
else
    print_status 1 "WhatsApp worker container is NOT running"
    echo -e "${YELLOW}Run: docker-compose up -d celery_worker${NC}"
fi

# Check Football worker
if docker ps | grep -q "whatsappcrm_celery_worker_football"; then
    print_status 0 "Football worker container is running"
else
    print_status 1 "Football worker container is NOT running"
    echo -e "${YELLOW}Run: docker-compose up -d celery_worker_football${NC}"
fi

# Check Redis
if docker ps | grep -q "whatsappcrm_redis"; then
    print_status 0 "Redis container is running"
else
    print_status 1 "Redis container is NOT running"
    echo -e "${YELLOW}Run: docker-compose up -d redis${NC}"
fi

echo ""
echo "2. Checking worker logs for errors..."
echo "================================================"

# Check WhatsApp worker logs for Redis errors
if docker logs whatsappcrm_celery_worker_whatsapp 2>&1 | tail -50 | grep -q "Cannot connect to redis"; then
    print_status 1 "WhatsApp worker has Redis connection errors"
    echo -e "${YELLOW}Check logs with: docker-compose logs celery_worker${NC}"
else
    print_status 0 "WhatsApp worker has no Redis errors"
fi

# Check Football worker logs for Redis errors
if docker logs whatsappcrm_celery_worker_football 2>&1 | tail -50 | grep -q "Cannot connect to redis"; then
    print_status 1 "Football worker has Redis connection errors"
    echo -e "${YELLOW}Check logs with: docker-compose logs celery_worker_football${NC}"
else
    print_status 0 "Football worker has no Redis errors"
fi

echo ""
echo "3. Testing worker connectivity..."
echo "================================================"

# Test WhatsApp worker ping
if docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend.celery inspect ping 2>&1 | grep -q "pong"; then
    print_status 0 "WhatsApp worker responds to ping"
else
    print_status 1 "WhatsApp worker does NOT respond to ping"
fi

# Test Football worker ping
if docker exec -it whatsappcrm_celery_worker_football celery -A whatsappcrm_backend.celery inspect ping 2>&1 | grep -q "pong"; then
    print_status 0 "Football worker responds to ping"
else
    print_status 1 "Football worker does NOT respond to ping"
fi

echo ""
echo "4. Checking worker queues..."
echo "================================================"

# Check WhatsApp worker queue
WA_QUEUE=$(docker exec whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend.celery inspect active_queues 2>&1 | grep -o "whatsapp" | head -1)
if [ "$WA_QUEUE" = "whatsapp" ]; then
    print_status 0 "WhatsApp worker is listening to 'whatsapp' queue"
else
    print_status 1 "WhatsApp worker is NOT listening to 'whatsapp' queue"
fi

# Check Football worker queue
FB_QUEUE=$(docker exec whatsappcrm_celery_worker_football celery -A whatsappcrm_backend.celery inspect active_queues 2>&1 | grep -o "football_data" | head -1)
if [ "$FB_QUEUE" = "football_data" ]; then
    print_status 0 "Football worker is listening to 'football_data' queue"
else
    print_status 1 "Football worker is NOT listening to 'football_data' queue"
fi

echo ""
echo "5. Checking registered tasks..."
echo "================================================"

# Count registered tasks on WhatsApp worker
WA_TASKS=$(docker exec whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend.celery inspect registered 2>&1 | grep -c "task" || echo "0")
print_status 0 "WhatsApp worker has $WA_TASKS task registrations"

# Count registered tasks on Football worker
FB_TASKS=$(docker exec whatsappcrm_celery_worker_football celery -A whatsappcrm_backend.celery inspect registered 2>&1 | grep -c "task" || echo "0")
print_status 0 "Football worker has $FB_TASKS task registrations"

echo ""
echo "6. Redis connectivity test..."
echo "================================================"

# Test Redis connection
if docker exec whatsappcrm_redis redis-cli -a mindwell ping 2>&1 | grep -q "PONG"; then
    print_status 0 "Redis is accessible and responding"
else
    print_status 1 "Redis is NOT accessible or password is incorrect"
    echo -e "${YELLOW}Check REDIS_PASSWORD in .env file${NC}"
fi

echo ""
echo "=========================================="
echo "Verification Complete!"
echo "=========================================="
echo ""
echo "To view detailed worker information:"
echo "  - WhatsApp worker logs: docker-compose logs -f celery_worker"
echo "  - Football worker logs: docker-compose logs -f celery_worker_football"
echo "  - Redis logs: docker-compose logs -f redis"
echo ""
echo "To check active tasks:"
echo "  - WhatsApp: docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend.celery inspect active"
echo "  - Football: docker exec -it whatsappcrm_celery_worker_football celery -A whatsappcrm_backend.celery inspect active"
echo ""
