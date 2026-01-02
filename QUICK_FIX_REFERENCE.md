# Quick Fix Reference - Task Registration Issue

## What Was Wrong?

Tasks from PR #58 were not showing up in Django Admin because:
- `__init__.py` imported `run_api_football_v3_full_update` (an alias)
- But it should import `run_api_football_v3_full_update_task` (the main task)

## What Was Fixed?

Changed 1 line in `whatsappcrm_backend/football_data_app/__init__.py`:
```diff
- run_api_football_v3_full_update,
+ run_api_football_v3_full_update_task,
```

## What Do I Do Now?

### Step 1: Merge This PR
Merge this PR into your main branch.

### Step 2: Restart Services
```bash
docker-compose restart backend celery_beat celery_cpu_worker
```

### Step 3: Verify Tasks Appear
Go to Django Admin → DJANGO CELERY BEAT → Periodic Tasks → Add Periodic Task

In the "Task (registered)" dropdown, you should now see:
- ✅ `football_data_app.run_api_football_v3_full_update`
- ✅ `football_data_app.run_score_and_settlement_v3_task`

### Step 4: First-Time Setup (if not done yet)
```bash
# Initialize leagues from API-Football v3
docker-compose exec backend python manage.py football_league_setup_v3
```

### Step 5: Schedule the Tasks

**Task 1: Data Update**
- Name: `Football Data Update`
- Task: `football_data_app.run_api_football_v3_full_update`
- Interval: Every 10 Minutes
- Queue: `football_data`

**Task 2: Score & Settlement**
- Name: `Score and Settlement`
- Task: `football_data_app.run_score_and_settlement_v3_task`
- Interval: Every 5 Minutes
- Queue: `football_data`

## Season Fields

The season fields are already editable:
- Edit `League.league_season`: Go to Leagues → Edit any league → "Season & Status" section
- Edit `Configuration.current_season`: Go to Configurations → Edit → "API Configuration" section

## Need More Help?

See `TASK_REGISTRATION_ISSUE_FIX.md` for complete documentation.
