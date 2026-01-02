# Task Registration Issue - Fix Summary

## Issue Description

Users reported that:
1. Tasks from PR #58 (API-Football v3 tasks) were not appearing in Django Admin's "Periodic Tasks" dropdown
2. The season fields (`league_season` and `current_season`) were not editable in Django Admin

## Root Cause

The `football_data_app/__init__.py` file was importing **alias functions** instead of the **main task functions**, causing tasks to be registered with incorrect names in Celery.

### The Problem

In `tasks_api_football_v3.py`:
- **Main task**: `run_api_football_v3_full_update_task()` with name `"football_data_app.run_api_football_v3_full_update"`
- **Alias task**: `run_api_football_v3_full_update()` with name `"football_data_app.run_api_football_v3_full_update_alias"`

The `__init__.py` was importing the **alias** (`run_api_football_v3_full_update`), which registered the task with the **wrong name** (`...alias`).

## Solution

### 1. Fixed Task Imports

**Changed in `whatsappcrm_backend/football_data_app/__init__.py`:**

```python
# Before (WRONG):
from .tasks_api_football_v3 import (
    run_api_football_v3_full_update,  # ❌ This is the alias!
    ...
)

# After (CORRECT):
from .tasks_api_football_v3 import (
    run_api_football_v3_full_update_task,  # ✅ This is the main task!
    ...
)
```

This ensures tasks are registered with the correct names:
- ✅ `football_data_app.run_api_football_v3_full_update`
- ✅ `football_data_app.run_score_and_settlement_v3_task`

### 2. Season Fields Already Fixed

The admin configuration was already correct (from PR #59):

**League Admin** (`whatsappcrm_backend/football_data_app/admin.py` line 23-29):
```python
fieldsets = (
    ...
    ('Season & Status', {
        'fields': ('league_season', 'active')  # ✅ league_season is editable
    }),
    ...
)
```

**Configuration Admin** (`whatsappcrm_backend/football_data_app/admin.py` line 149-155):
```python
fieldsets = (
    ...
    ('API Configuration', {
        'fields': ('api_key', 'current_season')  # ✅ current_season is editable
    }),
    ...
)
```

## Verification Steps

### 1. Restart Django and Celery Services

After this fix, you **must** restart the services to reload task registrations:

```bash
docker-compose restart backend celery_beat celery_cpu_worker
```

### 2. Verify Tasks Are Registered

Check that tasks appear in Celery's registered tasks list:

```bash
docker-compose exec backend python manage.py shell
```

Then in the Python shell:
```python
from celery import current_app
tasks = [task for task in current_app.tasks.keys() if 'football_data_app' in task]
for task in sorted(tasks):
    print(task)
```

**Expected output should include:**
```
football_data_app.run_api_football_v3_full_update
football_data_app.run_score_and_settlement_v3_task
football_data_app.run_apifootball_full_update
football_data_app.run_score_and_settlement_task
... (and other football tasks)
```

### 3. Verify Tasks in Django Admin

1. Navigate to: `http://your-domain/admin/`
2. Go to **DJANGO CELERY BEAT → Periodic Tasks**
3. Click **"Add Periodic Task"**
4. In the **"Task (registered)"** dropdown, you should now see:
   - `football_data_app.run_api_football_v3_full_update` ✅
   - `football_data_app.run_score_and_settlement_v3_task` ✅
   - `football_data_app.run_apifootball_full_update` (legacy)
   - `football_data_app.run_score_and_settlement_task` (legacy)

### 4. Verify Season Fields Are Editable

**For League Season:**
1. Go to **FOOTBALL DATA APP → Leagues**
2. Click on any league
3. You should see a **"Season & Status"** section with:
   - `league_season` field (editable text field)
   - `active` checkbox

**For Current Season:**
1. Go to **FOOTBALL DATA APP → Configurations**
2. Click on a configuration or add a new one
3. You should see an **"API Configuration"** section with:
   - `api_key` field (editable text field)
   - `current_season` field (editable integer field)

## How to Schedule Tasks

### Option 1: API-Football v3 (Recommended)

**Prerequisites:**
1. Get an API key from [api-football.com](https://www.api-football.com/)
2. Create a Configuration in Django Admin:
   - Provider Name: `API-Football`
   - API Key: `your_api_key`
   - Current Season: `2024` (or current year)
   - Is Active: ✓ checked

3. Run the setup command:
   ```bash
   docker-compose exec backend python manage.py football_league_setup_v3
   ```

**Schedule the Tasks:**

**Task 1: Football Data Update (API-Football v3)**
- Name: `Football Data Update (API-Football v3)`
- Task: `football_data_app.run_api_football_v3_full_update`
- Interval: Every 10 Minutes
- Queue: `football_data`
- Enabled: ✓

**Task 2: Score and Settlement (API-Football v3)**
- Name: `Score and Settlement (API-Football v3)`
- Task: `football_data_app.run_score_and_settlement_v3_task`
- Interval: Every 5 Minutes
- Queue: `football_data`
- Enabled: ✓

### Option 2: Legacy Provider (APIFootball.com without dash)

**Prerequisites:**
1. Get an API key from [apifootball.com](https://apifootball.com/)
2. Add to `.env`: `API_FOOTBALL_KEY=your_api_key`
3. Run setup: `docker-compose exec backend python manage.py football_league_setup`

**Schedule the Tasks:**

**Task 1: Football Data Update (Legacy)**
- Name: `Football Data Update (Legacy)`
- Task: `football_data_app.run_apifootball_full_update`
- Interval: Every 10 Minutes
- Queue: `cpu_heavy`
- Enabled: ✓

**Task 2: Score and Settlement (Legacy)**
- Name: `Score and Settlement (Legacy)`
- Task: `football_data_app.run_score_and_settlement_task`
- Interval: Every 5 Minutes
- Queue: `cpu_heavy`
- Enabled: ✓

## Troubleshooting

### Tasks Still Not Showing in Dropdown

1. **Restart services**: `docker-compose restart backend celery_beat celery_cpu_worker`
2. **Check for import errors**: `docker-compose logs backend | grep -i error`
3. **Verify task registration**: Use the verification steps above

### Season Fields Not Editable

1. **Clear browser cache**: Ctrl+Shift+R (or Cmd+Shift+R on Mac)
2. **Check admin registration**: Ensure `@admin.register(League)` and `@admin.register(Configuration)` decorators are present
3. **Restart Django**: `docker-compose restart backend`

### ImportError When Starting Services

If you see import errors related to tasks:
1. Check that all dependencies are installed: `docker-compose exec backend pip list | grep -i celery`
2. Ensure the database is migrated: `docker-compose exec backend python manage.py migrate`
3. Check for typos in import statements

## Summary of Changes

### Files Modified
1. `whatsappcrm_backend/football_data_app/__init__.py`
   - Fixed: Changed `run_api_football_v3_full_update` → `run_api_football_v3_full_update_task`
   - Impact: Tasks now register with correct names in Celery

### Files Already Correct (No Changes Needed)
1. `whatsappcrm_backend/football_data_app/admin.py`
   - League admin has `league_season` in fieldsets ✅
   - Configuration admin has `current_season` in fieldsets ✅
2. `whatsappcrm_backend/football_data_app/models.py`
   - `League.league_season` field exists ✅
   - `Configuration.current_season` field exists ✅
3. `whatsappcrm_backend/football_data_app/tasks_api_football_v3.py`
   - Tasks correctly defined with proper names ✅

## Related Documentation

- [TASK_REGISTRATION_FIX.md](TASK_REGISTRATION_FIX.md) - Original fix documentation from PR #59
- [FOOTBALL_TASKS_SETUP_GUIDE.md](FOOTBALL_TASKS_SETUP_GUIDE.md) - Complete setup guide
- [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md) - API-Football v3 details
- [SCHEDULED_TASKS_SETUP.md](SCHEDULED_TASKS_SETUP.md) - General task scheduling

## Questions?

If you encounter issues after applying this fix:
1. Check the troubleshooting section above
2. Review the logs: `docker-compose logs backend celery_beat celery_cpu_worker`
3. Verify services are running: `docker-compose ps`
4. Ensure the setup commands were run (see "How to Schedule Tasks" section)
