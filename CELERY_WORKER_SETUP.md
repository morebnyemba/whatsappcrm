# Celery Worker Configuration Guide

## Overview

This document explains the Celery worker setup for the WhatsApp CRM application, which now uses **two separate workers** for better task isolation and performance optimization.

> **⚠️ SECURITY NOTE**: The `.env` files in this repository contain sensitive credentials and should NOT be committed to version control in production deployments. Use `.env.example` as a template and ensure `.env` files are properly excluded via `.gitignore`.

## Problem Statement

The original issue encountered was:
1. **Redis Authentication Failure**: `invalid username-password pair or user is disabled`
2. **Need for Separate Workers**: One for football data processing and another for WhatsApp-based tasks

## Solution Implemented

### 1. Fixed Redis Authentication

**Issue**: The `.env` file used shell variable substitution syntax `${REDIS_PASSWORD}` which doesn't work with Python's `dotenv` library.

**Fix**: Updated the `CELERY_BROKER_URL` to use the actual password value:
```bash
# Before (incorrect)
CELERY_BROKER_URL='redis://:${REDIS_PASSWORD}@redis:6379/0'

# After (correct)
CELERY_BROKER_URL='redis://:your_redis_password@redis:6379/0'
```

### 2. Created Separate Celery Workers

Two specialized workers are now configured:

#### **WhatsApp Worker** (`celery_io_worker`)
- **Container Name**: `whatsappcrm_celery_worker_whatsapp`
- **Queue**: `whatsapp` (default queue)
- **Pool Type**: `gevent` (for I/O-bound tasks)
- **Concurrency**: 100 (configurable via `CELERY_WORKER_CONCURRENCY`)
- **Handles**:
  - WhatsApp message sending/receiving
  - Meta integration tasks
  - Conversation management
  - Flow processing
  - Customer data operations
  - Paynow integration
  - Referral tasks
  - Media management

#### **Football Data Worker** (`celery_worker_football`)
- **Container Name**: `whatsappcrm_celery_cpu_worker`
- **Queue**: `football_data`
- **Pool Type**: `prefork` (for CPU-bound tasks)
- **Concurrency**: 4 workers
- **Handles**:
  - Football fixture fetching
  - Odds updates
  - Score fetching
  - Bet settlement
  - Ticket processing

### 3. Task Routing Configuration

The `celery.py` file now includes automatic task routing:

```python
app.conf.task_routes = {
    # Football data tasks go to the football_data queue
    'football_data_app.tasks.*': {'queue': 'football_data'},
    'football_data_app.tasks_apifootball.*': {'queue': 'football_data'},
    
    # WhatsApp and general business tasks go to the whatsapp queue
    'meta_integration.tasks.*': {'queue': 'whatsapp'},
    'conversations.tasks.*': {'queue': 'whatsapp'},
    'flows.tasks.*': {'queue': 'whatsapp'},
    'customer_data.tasks.*': {'queue': 'whatsapp'},
    'paynow_integration.tasks.*': {'queue': 'whatsapp'},
    'referrals.tasks.*': {'queue': 'whatsapp'},
    'media_manager.tasks.*': {'queue': 'whatsapp'},
}
```

## Benefits

1. **Task Isolation**: Football data processing won't interfere with WhatsApp message handling
2. **Optimized Performance**: 
   - Gevent pool for I/O-bound WhatsApp tasks (handles many concurrent connections)
   - Prefork pool for CPU-bound football data tasks (better for data processing)
3. **Better Resource Management**: Each worker can be scaled independently
4. **Improved Reliability**: If one worker crashes, the other continues operating

## Docker Compose Services

The `docker-compose.yml` now includes three Celery-related services:

1. **celery_io_worker** (WhatsApp worker)
2. **celery_worker_football** (Football data worker)
3. **celery_beat** (Scheduler for periodic tasks)

> **⚠️ Important**: After deployment, you must configure periodic tasks in Django Admin. See [SCHEDULED_TASKS_SETUP.md](SCHEDULED_TASKS_SETUP.md) for detailed instructions on scheduling football data updates and bet settlement tasks.

## Environment Variables

Key environment variables in `.env`:

```bash
# Redis Configuration
REDIS_PASSWORD=your_redis_password
CELERY_BROKER_URL='redis://:your_redis_password@redis:6379/0'

# Worker Configuration (for WhatsApp worker only)
CELERY_WORKER_POOL_TYPE=gevent
CELERY_WORKER_CONCURRENCY=100
```

## Deployment

To deploy the updated configuration:

```bash
# Stop existing containers
docker-compose down

# Rebuild and start with new configuration
docker-compose up -d --build

# Verify workers are running
docker-compose ps

# Check worker logs
docker-compose logs -f celery_worker
docker-compose logs -f celery_worker_football
```

## Monitoring

To check if tasks are being routed correctly:

```bash
# Monitor WhatsApp worker
docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend inspect active

# Monitor Football worker
docker exec -it whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect active

# Check registered tasks
docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend inspect registered
```

## Troubleshooting

### Redis Connection Issues

If you see authentication errors:
1. Verify `REDIS_PASSWORD` matches in all locations:
   - Root `.env` file
   - `whatsappcrm_backend/.env` file
   - `docker-compose.yml` redis service
2. Check the Redis service is running:
   ```bash
   docker-compose ps redis
   docker-compose logs redis
   ```

### Worker Not Processing Tasks

1. Check worker logs for errors:
   ```bash
   docker-compose logs celery_worker
   docker-compose logs celery_worker_football
   ```

2. Verify workers are connected to Redis:
   ```bash
   docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend inspect ping
   ```

3. Check task routing configuration in `celery.py`

### Tasks Going to Wrong Queue

Verify the task module path matches the routing rules in `celery.py`. For example:
- `football_data_app.tasks.fetch_odds_for_single_event_task` → `football_data` queue
- `meta_integration.tasks.send_whatsapp_message_task` → `whatsapp` queue

## Scaling

To scale workers independently:

```bash
# Scale WhatsApp worker to 2 instances
docker-compose up -d --scale celery_io_worker=2

# Scale Football worker to 3 instances
docker-compose up -d --scale celery_worker_football=3
```

Note: When scaling, you'll need to remove the `container_name` directives or use different names.

## Future Improvements

Consider:
1. Adding Flower for web-based monitoring
2. Implementing task prioritization
3. Adding more specialized workers for different task types
4. Setting up alerts for failed tasks
5. Implementing circuit breakers for external API calls
