# Celery Task Queue Routing Fix

## Issue
Celery Beat was dispatching the `run_apifootball_full_update` task, but no Celery worker was picking it up.

## Root Cause
When the initial performance improvements removed task routing configuration, ALL tasks started going to the default queue. This meant:
- Football data tasks (like `run_apifootball_full_update`) were being sent to the default queue
- The `football_data` worker was listening to the `football_data` queue
- Since tasks weren't going to the right queue, the worker couldn't pick them up

## Solution
Restored task routing configuration while keeping performance improvements:

```python
# Configure task routing for separate workers
app.conf.task_routes = {
    # Football data tasks go to the football_data queue
    'football_data_app.*': {'queue': 'football_data'},
    'football_data_app.tasks.*': {'queue': 'football_data'},
    'football_data_app.tasks_apifootball.*': {'queue': 'football_data'},
    
    # WhatsApp and general business tasks go to the celery queue for fast processing
    'meta_integration.tasks.*': {'queue': 'celery'},
    'conversations.tasks.*': {'queue': 'celery'},
    'flows.tasks.*': {'queue': 'celery'},
    'customer_data.tasks.*': {'queue': 'celery'},
    'paynow_integration.tasks.*': {'queue': 'celery'},
    'referrals.tasks.*': {'queue': 'celery'},
    'media_manager.tasks.*': {'queue': 'celery'},
}

# Default queue for any tasks not explicitly routed
app.conf.task_default_queue = 'celery'
```

## Key Changes from Original
1. **Changed default queue from 'whatsapp' to 'celery'**: This provides better performance for business tasks
2. **Kept gevent removal**: Still no gevent overhead, maintaining performance improvements
3. **Preserved queue separation**: Football tasks and business tasks still use separate queues for better resource management

## Worker Configuration Required

You need to run TWO separate workers:

### Football Data Worker
```bash
celery -A whatsappcrm_backend worker -Q football_data -l info --concurrency=2
```
This worker handles:
- `run_apifootball_full_update`
- All other `football_data_app.*` tasks
- Heavy data processing tasks

### Business/WhatsApp Worker
```bash
celery -A whatsappcrm_backend worker -Q celery -l info --concurrency=4
```
This worker handles:
- Flow processing (`process_flow_for_message_task`)
- Message sending tasks
- Customer data tasks
- Payment tasks
- All time-sensitive business tasks

## Verification

After deploying, verify tasks are routing correctly:

1. **Check task routing in logs**:
   ```
   # Should see tasks being routed to correct queues
   [INFO] Task football_data_app.tasks_apifootball.run_apifootball_full_update[...] received on queue: football_data
   [INFO] Task flows.tasks.process_flow_for_message_task[...] received on queue: celery
   ```

2. **Monitor queue depth**:
   ```bash
   # Check Redis for queue lengths
   redis-cli -h localhost -p 6379
   > LLEN celery
   > LLEN football_data
   ```

3. **Test Celery Beat dispatch**:
   - Wait for scheduled task to run
   - Check that `football_data` worker picks it up
   - Verify in worker logs

## Benefits

✅ **Fixed**: Football data tasks now route to correct queue  
✅ **Maintained**: Performance improvements (no gevent, faster queue for business tasks)  
✅ **Improved**: Better queue naming (`celery` vs `whatsapp`)  
✅ **Scalable**: Can run multiple workers per queue as needed
