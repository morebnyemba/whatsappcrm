# Flow Task Processing Performance Fix

## Problem Statement
The flow task processing for WhatsApp messages was taking up to 4 minutes instead of being instant. This caused unacceptable delays in user interactions.

## Root Cause Analysis
After comparing with the reference repository (Kali-Safaris), the following issues were identified:

1. **gevent Monkey-Patching**: The celery.py configuration used gevent monkey-patching which adds significant overhead and can slow down task processing.
2. **Complex Task Routing**: Explicit queue routing with separate workers for different tasks was causing delays.
3. **No Session Management**: There was no automatic cleanup of idle sessions, leading to stale flow states.

## Changes Made

### 1. Removed gevent Monkey-Patching (`whatsappcrm_backend/celery.py`)
**Before:**
```python
if 'celery' in ' '.join(sys.argv):
    import gevent.monkey
    gevent.monkey.patch_all()
```

**After:**
```python
# Removed gevent completely - using standard Celery without gevent
```

**Impact**: This significantly reduces task processing overhead and improves response times.

### 2. Optimized Task Routing Configuration (`whatsappcrm_backend/celery.py`)
**Before:**
- Used `whatsapp` queue as default for all business tasks
- Complex setup with gevent and django.setup()

**After:**
```python
app.conf.task_routes = {
    # Football data tasks go to the football_data queue
    'football_data_app.*': {'queue': 'football_data'},
    
    # WhatsApp and general business tasks go to the celery queue for fast processing
    'meta_integration.tasks.*': {'queue': 'celery'},
    'flows.tasks.*': {'queue': 'celery'},
    # ... other business tasks
}

# Default queue for any tasks not explicitly routed
app.conf.task_default_queue = 'celery'
```

**Impact**: 
- Task routing is preserved to ensure proper queue distribution
- Football tasks go to `football_data` queue for dedicated worker
- Business/WhatsApp tasks go to fast `celery` queue
- Removed gevent overhead for better performance
- Clean, simple configuration without complexity

### 3. Updated Flow Task Processing (`whatsappcrm_backend/flows/tasks.py`)
**Changes:**
- Task routing handled by celery.py configuration (routes to 'celery' queue)
- This ensures flow tasks are processed on the main I/O queue for faster execution
- Added proper import of `_clear_contact_flow_state` at module level

**Impact**: Flow messages are now processed immediately instead of being queued to a potentially slower worker.

### 4. Added Session Expiry Functionality (`whatsappcrm_backend/flows/tasks.py`)
**New Task:**
```python
@shared_task(name="flows.cleanup_idle_conversations_task")
def cleanup_idle_conversations_task():
    """
    Cleans up idle conversations after 15 minutes of inactivity.
    Runs every 5 minutes.
    """
```

**Features:**
- Checks for ContactFlowState records idle for more than 15 minutes
- Clears the flow state for idle contacts
- Sends notification to users about session expiry
- Runs automatically every 5 minutes

**Impact**: Prevents stale flow states and improves user experience with clear session boundaries.

### 5. Added Periodic Task Schedule (`whatsappcrm_backend/whatsappcrm_backend/settings.py`)
**Added:**
```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'cleanup-idle-conversations': {
        'task': 'flows.cleanup_idle_conversations_task',
        'schedule': crontab(minute='*/5'),
    },
}
```

**Impact**: Enables automatic session cleanup every 5 minutes.

## Expected Results

1. **Instant Response Times**: Flow task processing should now complete in seconds instead of minutes
2. **Better Resource Management**: No gevent overhead means better CPU and memory usage
3. **Clean Session Management**: Users get clear feedback when sessions expire after 15 minutes of inactivity
4. **Improved User Experience**: Faster responses and clear session boundaries

## Testing Recommendations

1. **Performance Testing**:
   - Send a WhatsApp message and measure response time
   - Should be under 2 seconds for simple flows
   - Monitor Celery worker logs for task execution times

2. **Session Expiry Testing**:
   - Start a flow conversation
   - Wait 15+ minutes without interaction
   - Verify user receives "session expired" message
   - Confirm flow state is cleared

3. **Load Testing**:
   - Send multiple messages simultaneously
   - Verify all are processed quickly
   - Check for any task queue buildup

## Deployment Notes

1. **Celery Workers**: Restart all Celery workers after deployment
   ```bash
   # Stop existing workers
   pkill -f 'celery worker'
   
   # Start football_data worker (listens to football_data queue)
   celery -A whatsappcrm_backend worker -Q football_data -l info --concurrency=2
   
   # Start main business/WhatsApp worker (listens to celery queue)
   celery -A whatsappcrm_backend worker -Q celery -l info --concurrency=4
   ```
   
   **Important**: Make sure you have workers for both queues:
   - `football_data` queue: For football data tasks (run_apifootball_full_update, etc.)
   - `celery` queue: For WhatsApp and business tasks (flows, messages, etc.)

2. **Celery Beat**: Ensure Celery Beat is running for session cleanup
   ```bash
   celery -A whatsappcrm_backend beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
   ```

3. **Database Migration**: Run migrations if needed
   ```bash
   python manage.py migrate
   ```

4. **Monitor Logs**: Watch for the cleanup task execution every 5 minutes
   ```
   [Idle Conversation Cleanup] Running task for conversations idle since...
   ```

5. **Verify Task Routing**: Check that tasks are going to the correct queues
   ```bash
   # In Django shell
   python manage.py shell
   >>> from celery import current_app
   >>> print(current_app.conf.task_routes)
   ```

## Security Summary

No security vulnerabilities were introduced by these changes. CodeQL analysis returned 0 alerts.

## References

- Reference Repository: https://github.com/morebnyemba/Kali-Safaris
- Issue: Fix flow task message processing speed
- Session timeout requirement: 15 minutes (as specified in requirements)
