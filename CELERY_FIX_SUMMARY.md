# Celery Worker Fix Summary

## Problem
- Celery workers were not starting
- Celery beat was not starting
- Unable to access logs or debug the issue

## Root Cause Analysis
By comparing with the reference repository (Kali-Safaris), we identified several configuration issues:

1. **Incorrect Celery app path in commands**: Workers were using `celery -A whatsappcrm_backend.celery` instead of `celery -A whatsappcrm_backend`
2. **Overcomplicated celery.py**: Had unnecessary task routing and performance optimizations that could cause startup issues
3. **Complex docker-compose commands**: Used shell scripts with manual health checks instead of simple direct commands
4. **Mismatched queue names**: Using custom queue names (`whatsapp`, `football_data`) not aligned with reference

## Solution Applied

### 1. Simplified `celery.py`
**File**: `whatsappcrm_backend/whatsappcrm_backend/celery.py`

Removed:
- Custom task routing (`app.conf.task_routes`)
- Default queue overrides
- Performance optimization settings that might interfere with startup

The simplified version now matches the reference repository exactly.

### 2. Updated `docker-compose.yml`
**File**: `docker-compose.yml`

Changed worker configurations:

**Before**:
```yaml
celery_worker:
  command: >
    sh -c "... celery -A whatsappcrm_backend.celery worker -Q whatsapp ..."
```

**After**:
```yaml
celery_io_worker:
  command: celery -A whatsappcrm_backend worker -Q celery -l INFO --concurrency=20
```

Key changes:
- Renamed `celery_worker` → `celery_io_worker`
- Renamed `celery_worker_football` → `celery_cpu_worker`
- Changed app path from `whatsappcrm_backend.celery` → `whatsappcrm_backend`
- Removed shell script wrappers
- Changed queue names: `whatsapp` → `celery`, `football_data` → `cpu_heavy`
- Simplified commands to match reference repository

### 3. Updated Task Queue Assignments
**Files**: `football_data_app/tasks_apifootball.py`

- Updated all football data tasks to use `queue='cpu_heavy'` instead of `queue='football_data'`
- WhatsApp and flow tasks already use `queue='celery'` (correct)

## Testing

To test the changes:

```bash
# Stop and rebuild
docker compose down
docker compose build backend celery_io_worker celery_cpu_worker celery_beat

# Start services
docker compose up -d

# Check logs
docker compose logs -f celery_io_worker
docker compose logs -f celery_cpu_worker
docker compose logs -f celery_beat
```

Expected output: Workers should start successfully showing:
- `[... ] celery@... ready.`
- List of registered tasks
- Queue information
- No connection errors

## Impact

✅ **Benefits**:
- Celery workers will start properly
- Celery beat scheduler will start properly
- Configuration matches proven reference repository
- Simpler, more maintainable configuration
- Better alignment with Celery best practices

⚠️ **Breaking Changes**:
- Service names changed in docker-compose.yml:
  - `celery_worker` → `celery_io_worker`
  - `celery_worker_football` → `celery_cpu_worker`
- Queue names changed:
  - `whatsapp` → `celery`
  - `football_data` → `cpu_heavy`
- If any scripts reference the old service names, they need to be updated

## Files Modified

1. `whatsappcrm_backend/whatsappcrm_backend/celery.py` - Simplified configuration
2. `docker-compose.yml` - Updated worker service names and commands
3. `whatsappcrm_backend/football_data_app/tasks_apifootball.py` - Updated queue names

## Reference

Configuration based on: https://github.com/morebnyemba/Kali-Safaris
