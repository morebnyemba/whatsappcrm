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

# Check IO worker (handles WhatsApp, flows, general tasks)
if docker ps | grep -q "whatsappcrm_celery_io_worker"; then
    print_status 0 "I/O worker container is running"
else
    print_status 1 "I/O worker container is NOT running"
    echo -e "${YELLOW}Run: docker compose up -d celery_io_worker${NC}"
fi

# Check CPU worker (handles football data tasks)
if docker ps | grep -q "whatsappcrm_celery_cpu_worker"; then
    print_status 0 "CPU worker container is running"
else
    print_status 1 "CPU worker container is NOT running"
    echo -e "${YELLOW}Run: docker compose up -d celery_cpu_worker${NC}"
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

# Check I/O worker logs for Redis errors
if docker logs whatsappcrm_celery_io_worker 2>&1 | tail -50 | grep -q "Cannot connect to redis"; then
    print_status 1 "I/O worker has Redis connection errors"
    echo -e "${YELLOW}Check logs with: docker compose logs celery_io_worker${NC}"
else
    print_status 0 "I/O worker has no Redis errors"
fi

# Check CPU worker logs for Redis errors
if docker logs whatsappcrm_celery_cpu_worker 2>&1 | tail -50 | grep -q "Cannot connect to redis"; then
    print_status 1 "CPU worker has Redis connection errors"
    echo -e "${YELLOW}Check logs with: docker compose logs celery_cpu_worker${NC}"
else
    print_status 0 "CPU worker has no Redis errors"
fi

echo ""
echo "3. Testing worker connectivity..."
echo "================================================"

# Test I/O worker ping
if docker exec whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect ping 2>&1 | grep -q "pong"; then
    print_status 0 "I/O worker responds to ping"
else
    print_status 1 "I/O worker does NOT respond to ping"
fi

# Test CPU worker ping
if docker exec whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect ping 2>&1 | grep -q "pong"; then
    print_status 0 "CPU worker responds to ping"
else
    print_status 1 "CPU worker does NOT respond to ping"
fi

echo ""
echo "4. Checking worker queues..."
echo "================================================"

# Check I/O worker queue
IO_QUEUE=$(docker exec whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect active_queues 2>&1 | grep -o "celery" | head -1)
if [ "$IO_QUEUE" = "celery" ]; then
    print_status 0 "I/O worker is listening to 'celery' queue"
else
    print_status 1 "I/O worker is NOT listening to 'celery' queue"
fi

# Check CPU worker queue
CPU_QUEUE=$(docker exec whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect active_queues 2>&1 | grep -o "cpu_heavy" | head -1)
if [ "$CPU_QUEUE" = "cpu_heavy" ]; then
    print_status 0 "CPU worker is listening to 'cpu_heavy' queue"
else
    print_status 1 "CPU worker is NOT listening to 'cpu_heavy' queue"
fi

echo ""
echo "5. Checking registered tasks..."
echo "================================================"

# Count registered tasks on I/O worker
IO_TASKS=$(docker exec whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect registered 2>&1 | grep -c "task" || echo "0")
print_status 0 "I/O worker has $IO_TASKS task registrations"

# Count registered tasks on CPU worker
CPU_TASKS=$(docker exec whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect registered 2>&1 | grep -c "task" || echo "0")
print_status 0 "CPU worker has $CPU_TASKS task registrations"

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
echo "  - I/O worker logs: docker compose logs -f celery_io_worker"
echo "  - CPU worker logs: docker compose logs -f celery_cpu_worker"
echo "  - Redis logs: docker compose logs -f redis"
echo ""
echo "To check active tasks:"
echo "  - I/O worker: docker exec whatsappcrm_celery_io_worker celery -A whatsappcrm_backend inspect active"
echo "  - CPU worker: docker exec whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect active"
echo ""
