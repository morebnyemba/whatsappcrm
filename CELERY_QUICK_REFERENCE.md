# Quick Reference: Celery Task Routing

## Task Queue Assignment

### Football Data Queue
All tasks in these modules are routed to the `football_data` queue:
- `football_data_app.tasks.*`
- `football_data_app.tasks_apifootball.*`

**Examples:**
```python
from football_data_app.tasks import run_apifootball_full_update_task
run_apifootball_full_update_task.apply_async()  # Routes to football_data queue
```

### WhatsApp Queue (Default)
All tasks in these modules are routed to the `whatsapp` queue:
- `meta_integration.tasks.*`
- `conversations.tasks.*`
- `flows.tasks.*`
- `customer_data.tasks.*`
- `paynow_integration.tasks.*`
- `referrals.tasks.*`
- `media_manager.tasks.*`

**Examples:**
```python
from meta_integration.tasks import send_whatsapp_message_task
send_whatsapp_message_task.apply_async(args=[message_id, config_id])  # Routes to whatsapp queue
```

## Adding New Tasks

When creating new tasks:

### For Football Data Tasks
Place your task file in `football_data_app/` and it will automatically route to `football_data` queue:
```python
# football_data_app/tasks.py or football_data_app/tasks_*.py
from celery import shared_task

@shared_task
def my_new_football_task():
    # This will automatically use the football_data queue
    pass
```

### For Other Business Logic Tasks
Place your task file in the appropriate app and it will route to `whatsapp` queue:
```python
# your_app/tasks.py
from celery import shared_task

@shared_task
def my_new_business_task():
    # This will automatically use the whatsapp queue
    pass
```

### Manual Queue Assignment
If you need to explicitly specify a queue:
```python
@shared_task
def my_task():
    pass

# Call with explicit queue
my_task.apply_async(queue='custom_queue')
```

## Checking Task Status

```python
from celery.result import AsyncResult

result = AsyncResult(task_id)
print(result.state)  # PENDING, STARTED, SUCCESS, FAILURE, RETRY
print(result.result)  # The return value or exception
```

## Common Commands

```bash
# Check active tasks on WhatsApp worker
docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend inspect active

# Check active tasks on Football worker
docker exec -it whatsappcrm_celery_worker_football celery -A whatsappcrm_backend inspect active

# List all registered tasks
docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend inspect registered

# Check worker stats
docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend inspect stats

# Purge all tasks from a queue
docker exec -it whatsappcrm_celery_worker_whatsapp celery -A whatsappcrm_backend purge -Q whatsapp

# Restart workers
docker-compose restart celery_worker celery_worker_football
```

## Worker Configuration Summary

| Worker | Queue | Pool | Concurrency | Use Case |
|--------|-------|------|-------------|----------|
| celery_worker_whatsapp | whatsapp | gevent | 100 | I/O-bound tasks (API calls, messaging) |
| celery_worker_football | football_data | prefork | 4 | CPU-bound tasks (data processing) |

## Environment Variables

```bash
# .env file
REDIS_PASSWORD=your_redis_password
CELERY_BROKER_URL='redis://:your_redis_password@redis:6379/0'
CELERY_WORKER_CONCURRENCY=100  # Only affects WhatsApp worker
CELERY_WORKER_POOL_TYPE=gevent  # Only affects WhatsApp worker
```

## Troubleshooting

### Task not executing
1. Check if worker is running: `docker-compose ps`
2. Check worker logs: `docker-compose logs -f celery_worker`
3. Verify task is registered: `celery inspect registered`
4. Check Redis connection: `docker-compose logs redis`

### Wrong worker processing task
Check task routing in `whatsappcrm_backend/celery.py` - the module path must match the routing rules.

### High memory usage
- For gevent workers: Reduce `CELERY_WORKER_CONCURRENCY`
- For prefork workers: Reduce `-c` parameter in docker-compose.yml

### Slow task execution
- Check if CPU-bound tasks are on gevent pool (should be prefork)
- Check if I/O-bound tasks are on prefork pool (should be gevent)
- Monitor with: `docker stats`
