# Fix Summary: Task Registration and Admin Field Issues

This document explains the fixes implemented to address the issues reported in #58.

## Issues Fixed

### 1. Tasks from PR #58 Not Registered in Django Admin

**Problem**: The football tasks from `tasks_api_football_v3.py` were not appearing in the Django Admin "Periodic Tasks" dropdown for scheduling.

**Root Cause**: Celery's autodiscovery mechanism requires tasks to be imported in the app's `__init__.py` file or be in a file named `tasks.py`. The tasks in `tasks_api_football_v3.py` were not being imported, so Celery couldn't discover them.

**Solution**: Updated `football_data_app/__init__.py` to import all tasks from both:
- `tasks_api_football_v3.py` (new API-Football v3 tasks)
- `tasks.py` (legacy tasks for backward compatibility)

**Tasks Now Available for Scheduling**:
- `football_data_app.run_api_football_v3_full_update` - Main task to fetch leagues, fixtures, and odds
- `football_data_app.run_score_and_settlement_v3_task` - Task to fetch scores and settle bets
- Plus all legacy tasks from `tasks_apifootball.py`

### 2. Season Fields Not Editable in Django Admin

**Problem**: Two season-related fields were not editable in the Django Admin:
- `League.league_season` - Used to store the season for each league (e.g., "2023/2024")
- `Configuration.current_season` - Used to configure the current season year (e.g., 2024)

**Root Cause**: The admin classes for these models did not define `fieldsets` or `fields`, which meant only fields in `list_display` were visible. The season fields were not included in the edit forms.

**Solution**: 
- **League Admin**: Added fieldsets to organize fields logically, included `league_season` in the "Season & Status" section
- **Configuration Admin**: Added `current_season` to the "API Configuration" fieldset

## How to Use the Fixed Features

### Scheduling Tasks in Django Admin

1. Navigate to Django Admin → **DJANGO CELERY BEAT > Periodic Tasks**
2. Click **"Add Periodic Task"**
3. In the "Task (registered)" dropdown, you should now see:
   - `football_data_app.run_api_football_v3_full_update`
   - `football_data_app.run_score_and_settlement_v3_task`
   - And all other football-related tasks

**Example Configuration**:
```
Name: Football Data Update (API-Football v3)
Task: football_data_app.run_api_football_v3_full_update
Interval: Every 10 Minutes
Queue: cpu_heavy
Enabled: ✓
```

### Editing Season Fields

#### To Edit League Season:
1. Navigate to Django Admin → **FOOTBALL DATA APP > Leagues**
2. Click on any league to edit
3. You'll see a "Season & Status" section where you can edit:
   - `league_season` - Enter the season (e.g., "2024/2025")
   - `active` - Toggle whether the league is tracked

#### To Edit Current Season for API Configuration:
1. Navigate to Django Admin → **FOOTBALL DATA APP > Configurations**
2. Click on a configuration entry to edit
3. In the "API Configuration" section, you'll see:
   - `api_key` - Your API key
   - `current_season` - The year to use for API calls (e.g., 2024)

## Important Notes

### First-Time Setup

Before scheduling any tasks, you **MUST** run the league setup command:

**For API-Football v3 (Recommended)**:
```bash
docker-compose exec backend python manage.py football_league_setup_v3
```

**For Legacy Provider**:
```bash
docker-compose exec backend python manage.py football_league_setup
```

### Task Naming Convention

- Tasks with `_v3` suffix use the new API-Football v3 provider (api-football.com with dash)
- Tasks without `_v3` suffix use the legacy provider (apifootball.com without dash)
- Both sets of tasks are now registered and available for scheduling

### Queue Configuration

All football tasks use the `football_data` queue. Ensure your Celery worker is configured to handle this queue:

```bash
docker-compose exec celery_cpu_worker celery -A whatsappcrm_backend inspect active_queues
```

## Verification

To verify the fixes are working:

1. **Check Tasks Are Registered**:
   ```bash
   docker-compose exec backend python manage.py shell
   >>> from celery import current_app
   >>> tasks = [task for task in current_app.tasks.keys() if 'football_data_app' in task]
   >>> for task in sorted(tasks):
   ...     print(task)
   ```
   
   You should see tasks like:
   - `football_data_app.run_api_football_v3_full_update`
   - `football_data_app.run_score_and_settlement_v3_task`

2. **Check Admin Fields**:
   - Go to Django Admin → Leagues → Click any league
   - Verify you see the "Season & Status" section with `league_season` field
   - Go to Django Admin → Configurations → Click any configuration
   - Verify you see `current_season` in the "API Configuration" section

## Related Documentation

For more detailed information, see:
- [FOOTBALL_TASKS_SETUP_GUIDE.md](FOOTBALL_TASKS_SETUP_GUIDE.md) - Complete setup guide
- [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md) - API-Football v3 integration details
- [SCHEDULED_TASKS_SETUP.md](SCHEDULED_TASKS_SETUP.md) - General scheduled tasks setup

## Troubleshooting

**Issue**: Tasks still not appearing in Django Admin dropdown
- **Solution**: Restart the Django application: `docker-compose restart backend`

**Issue**: Import errors when starting the application
- **Solution**: Check that all dependencies are installed: `docker-compose exec backend pip install -r requirements.txt`

**Issue**: Season field still not editable
- **Solution**: Clear browser cache and refresh Django Admin page
