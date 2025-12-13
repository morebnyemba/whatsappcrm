# Testing Instructions for Celery Worker Fix

## What Was Fixed

The Celery workers and beat scheduler were not starting. This has been fixed by aligning the configuration with the reference repository (Kali-Safaris).

## Key Changes

1. **Simplified celery.py** - Removed unnecessary task routing and configuration
2. **Updated docker-compose.yml** - Changed service names and simplified commands
3. **Updated queue names** - `whatsapp` → `celery`, `football_data` → `cpu_heavy`
4. **Updated service names**:
   - `celery_worker` → `celery_io_worker`
   - `celery_worker_football` → `celery_cpu_worker`

## How to Test

### Step 1: Stop Existing Containers
```bash
docker compose down
```

### Step 2: Rebuild Containers
```bash
docker compose build backend celery_io_worker celery_cpu_worker celery_beat
```

### Step 3: Start Services
```bash
docker compose up -d
```

### Step 4: Verify Workers Are Running

Check that all services are up:
```bash
docker compose ps
```

You should see:
- `whatsappcrm_celery_io_worker` - Up
- `whatsappcrm_celery_cpu_worker` - Up
- `whatsappcrm_celery_beat` - Up

### Step 5: Check Worker Logs

**I/O Worker** (handles WhatsApp, flows, general tasks):
```bash
docker compose logs -f celery_io_worker
```

Expected output:
```
celery@... v5.4.x (...)
[config]
.> app:         whatsappcrm_backend:...
.> transport:   redis://:**@redis:6379/0
.> results:     django-db
.> concurrency: 20 (prefork)

[queues]
.> celery           exchange=celery(direct) key=celery

[tasks]
  . meta_integration.tasks.send_whatsapp_message_task
  . flows.tasks.process_flow_message_task
  ...

[... ] celery@... ready.
```

**CPU Worker** (handles football data tasks):
```bash
docker compose logs -f celery_cpu_worker
```

Expected output:
```
celery@... v5.4.x (...)
[config]
.> app:         whatsappcrm_backend:...
.> transport:   redis://:**@redis:6379/0
.> results:     django-db
.> concurrency: 1 (prefork)

[queues]
.> cpu_heavy        exchange=cpu_heavy(direct) key=cpu_heavy

[tasks]
  . football_data_app.tasks_apifootball.run_apifootball_full_update_task
  ...

[... ] celery@... ready.
```

**Celery Beat**:
```bash
docker compose logs -f celery_beat
```

Expected output:
```
celery beat v5.4.x (...)
DatabaseScheduler: Schedule changed.
LocalTime -> ...
Configuration ->
    . broker -> redis://:**@redis:6379/0
    . loader -> celery.loaders.app.AppLoader
    . scheduler -> django_celery_beat.schedulers.DatabaseScheduler
[... ] beat: Starting...
```

### Step 6: Run Verification Script

```bash
./verify_celery_workers.sh
```

This script will check:
- ✓ Containers are running
- ✓ No Redis connection errors
- ✓ Workers respond to ping
- ✓ Workers are listening to correct queues
- ✓ Tasks are registered
- ✓ Redis connectivity

### Step 7: Test Task Execution

Test a simple task:
```bash
docker compose exec backend python manage.py shell
```

In the shell:
```python
from whatsappcrm_backend.celery import debug_task
result = debug_task.delay()
print(f"Task ID: {result.id}")
print(f"Task status: {result.status}")
# Should show: Task status: SUCCESS (or PENDING if still running)
```

Monitor task execution:
```bash
docker compose logs -f celery_io_worker | grep "Task"
```

## Troubleshooting

### Error: "Consumer: Cannot connect to redis"

**Solution**: Check Redis is running and password is correct
```bash
docker compose logs redis
# Verify CELERY_BROKER_URL in .env matches Redis password
```

### Error: Workers not showing as "ready"

**Solution**: Check for errors in logs
```bash
docker compose logs celery_io_worker | tail -50
docker compose logs celery_cpu_worker | tail -50
```

### Error: "No module named 'whatsappcrm_backend'"

**Solution**: Ensure WORKDIR is set correctly in Dockerfile (should be `/app`)

## Expected Results

✅ **Success Criteria**:
1. Both celery workers start without errors
2. Celery beat starts without errors
3. Workers show "ready" status in logs
4. Workers respond to ping commands
5. Tasks are registered and visible
6. Test task executes successfully

## Breaking Changes to Note

⚠️ **Service Name Changes**:
- Old: `celery_worker` → New: `celery_io_worker`
- Old: `celery_worker_football` → New: `celery_cpu_worker`

If you have scripts or monitoring that reference the old service names, update them to use the new names.

⚠️ **Queue Name Changes**:
- Old: `whatsapp` → New: `celery`
- Old: `football_data` → New: `cpu_heavy`

If you have any custom task definitions using the old queue names, update them.

## Next Steps

After confirming the workers are running:
1. Test WhatsApp message sending
2. Test flow processing
3. Test football data updates
4. Verify scheduled tasks are executing
5. Monitor for any issues in production

## Reference

For more details, see:
- `CELERY_FIX_SUMMARY.md` - Complete fix summary
- `verify_celery_workers.sh` - Automated verification script
- Reference repo: https://github.com/morebnyemba/Kali-Safaris
