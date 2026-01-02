# CPU Worker Task Pickup Issue - Fix Summary

## Issue Description

New tasks from API-Football v3 (in `tasks_api_football_v3.py`) were not being picked up by the CPU worker.

## Root Cause

The system had a queue name mismatch:

1. **CPU Worker Configuration** (in `docker-compose.yml`):
   - The `celery_cpu_worker` service was configured to listen to the `cpu_heavy` queue
   - Command: `celery -A whatsappcrm_backend worker -Q cpu_heavy -l INFO --concurrency=1`

2. **Legacy Tasks** (in `tasks_apifootball.py`):
   - All tasks were correctly using `queue='cpu_heavy'` ✅

3. **New V3 Tasks** (in `tasks_api_football_v3.py`):
   - All tasks were using `queue='football_data'` ❌
   - This meant they were **NOT being picked up** by the CPU worker

## Solution Applied

Changed all task decorators in `tasks_api_football_v3.py` from `queue='football_data'` to `queue='cpu_heavy'`.

### Files Modified

1. **`whatsappcrm_backend/football_data_app/tasks_api_football_v3.py`**
   - Updated 10 task decorators to use `queue='cpu_heavy'`:
     - `run_api_football_v3_full_update_task`
     - `fetch_and_update_leagues_v3_task`
     - `_prepare_and_launch_event_odds_chord_v3`
     - `fetch_events_for_league_v3_task`
     - `dispatch_odds_fetching_after_events_v3_task`
     - `fetch_odds_for_single_event_v3_task`
     - `run_score_and_settlement_v3_task`
     - `fetch_scores_for_league_v3_task`
     - `run_api_football_v3_full_update` (alias)
     - `run_score_and_settlement_v3` (alias)

2. **`TASK_REGISTRATION_FIX.md`**
   - Updated example configuration to show `Queue: cpu_heavy`

3. **`TASK_REGISTRATION_ISSUE_FIX.md`**
   - Updated documentation for v3 tasks to show `Queue: cpu_heavy`

## Verification Steps

After deploying this fix, verify that tasks are being picked up correctly:

### 1. Restart Celery Services

```bash
docker compose restart celery_cpu_worker celery_beat
```

### 2. Monitor CPU Worker Logs

```bash
docker compose logs -f celery_cpu_worker
```

You should see the worker starting up and listing registered tasks.

### 3. Schedule a Test Task

In Django Admin:
1. Go to **DJANGO CELERY BEAT → Periodic Tasks**
2. Add a new periodic task:
   - **Name**: Test API-Football v3 Update
   - **Task (registered)**: `football_data_app.run_api_football_v3_full_update`
   - **Interval**: Create a new interval (e.g., every 1 minute for testing)
   - **Queue**: `cpu_heavy`
   - **Enabled**: ✓ (checked)

3. Save the task

### 4. Verify Task Execution

Monitor the CPU worker logs:

```bash
docker compose logs -f celery_cpu_worker
```

Within a few minutes, you should see:
- `[INFO/MainProcess] Received task: football_data_app.run_api_football_v3_full_update`
- Task execution logs showing the task is running

### 5. Check Task Results

You can also check the task results in Django Admin:
1. Go to **DJANGO CELERY RESULTS → Task Results**
2. Look for tasks with name `football_data_app.run_api_football_v3_full_update`
3. Verify they have a status (SUCCESS, FAILURE, etc.)

## Testing with Docker

If you want to manually test a task:

```bash
# Execute a shell in the backend container
docker compose exec backend python manage.py shell

# In the Python shell:
from football_data_app.tasks_api_football_v3 import run_api_football_v3_full_update_task

# Trigger the task manually
result = run_api_football_v3_full_update_task.apply_async()

# Check the task ID
print(f"Task ID: {result.id}")
print(f"Task status: {result.status}")
```

Then monitor the CPU worker logs to see if it picks up the task.

## Expected Behavior After Fix

✅ **Before Fix**: New v3 tasks were sent to `football_data` queue, but no worker was listening to it, so tasks stayed queued forever.

✅ **After Fix**: New v3 tasks are sent to `cpu_heavy` queue, and the CPU worker picks them up and executes them.

## All Football Tasks Now Use `cpu_heavy` Queue

Both legacy and v3 tasks now use the same queue:

### Legacy Tasks (tasks_apifootball.py)
- `football_data_app.run_apifootball_full_update` → `cpu_heavy`
- `football_data_app.run_score_and_settlement_task` → `cpu_heavy`
- All supporting tasks → `cpu_heavy`

### V3 Tasks (tasks_api_football_v3.py)
- `football_data_app.run_api_football_v3_full_update` → `cpu_heavy`
- `football_data_app.run_score_and_settlement_v3_task` → `cpu_heavy`
- All supporting tasks → `cpu_heavy`

## Notes

- This fix aligns with the queue standardization done in previous PRs (see `CELERY_FIX_SUMMARY.md`)
- The queue was renamed from `football_data` to `cpu_heavy` to match the reference repository
- Both IO-bound tasks (in `celery_io_worker`) and CPU-bound tasks (in `celery_cpu_worker`) now follow consistent naming conventions

## Rollback Instructions (if needed)

If for any reason you need to rollback this change:

1. Revert the changes to `tasks_api_football_v3.py`:
   ```bash
   git revert <commit-hash>
   ```

2. Update the worker to listen to both queues:
   ```yaml
   celery_cpu_worker:
     command: celery -A whatsappcrm_backend worker -Q cpu_heavy,football_data -l INFO --concurrency=1
   ```

However, the recommended approach is to keep the standardized queue names.

## Related Documentation

- `CELERY_FIX_SUMMARY.md` - Previous queue standardization fix
- `CELERY_WORKER_SETUP.md` - Worker configuration guide
- `TASK_REGISTRATION_FIX.md` - Task registration documentation
- `docker-compose.yml` - Worker service definitions
