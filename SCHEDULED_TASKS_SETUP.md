# Scheduled Tasks Setup Guide

## Overview

This application uses **Celery Beat** with **django-celery-beat** to run periodic tasks. The Celery Beat scheduler is already configured in `docker-compose.yml` and reads task schedules from the database.

## Pre-configured Components

✅ **Celery Beat Service** - Running in Docker container `whatsappcrm_celery_beat`  
✅ **django-celery-beat** - Installed and configured in `settings.py`  
✅ **Database Scheduler** - Stores schedules in PostgreSQL  

## Tasks That Should Be Scheduled

The following tasks need to be scheduled via the Django admin panel:

### 1. Football Data Update Task
**Task Name**: `football_data_app.run_apifootball_full_update`

**Purpose**: Fetches football fixtures, leagues, and odds from APIFootball.com

**Recommended Schedule**: Every 10-15 minutes during active hours

**Configuration**:
- Interval: 10 minutes
- Enabled: Yes
- Queue: `football_data` (handled by football worker)

### 2. Score and Settlement Task
**Task Name**: `football_data_app.run_score_and_settlement_task`

**Purpose**: Fetches match scores and settles bets/tickets

**Recommended Schedule**: Every 5-10 minutes during match hours

**Configuration**:
- Interval: 5 minutes
- Enabled: Yes
- Queue: `football_data` (handled by football worker)

### 3. Delete Old Conversations (Optional)
**Task Name**: Can be configured via management command

**Purpose**: Clean up old conversation data

**Recommended Schedule**: Daily at 2 AM

## How to Set Up Scheduled Tasks

### Step 1: Access Django Admin

1. Start your services:
   ```bash
   docker-compose up -d
   ```

2. Access the admin panel:
   ```
   http://your-domain/admin/
   ```

3. Log in with your superuser credentials

### Step 2: Create Periodic Tasks

1. Navigate to **Periodic Tasks** section (under DJANGO CELERY BEAT)

2. Click **"Add Periodic Task"**

3. For **Football Data Update**:
   - **Name**: `Football Data Update`
   - **Task (registered)**: `football_data_app.run_apifootball_full_update`
   - **Interval**: Click the green + to create new interval
     - Every: `10`
     - Period: `Minutes`
   - **Queue**: `football_data`
   - **Enabled**: ✓ (checked)
   - Click **Save**

4. For **Score and Settlement**:
   - **Name**: `Score and Settlement`
   - **Task (registered)**: `football_data_app.run_score_and_settlement_task`
   - **Interval**: Click the green + to create new interval
     - Every: `5`
     - Period: `Minutes`
   - **Queue**: `football_data`
   - **Enabled**: ✓ (checked)
   - Click **Save**

### Step 3: Verify Tasks Are Running

Check the Celery Beat logs:
```bash
docker-compose logs -f celery_beat
```

You should see entries like:
```
[INFO] Scheduler: Sending due task football_data_app.run_apifootball_full_update
[INFO] Scheduler: Sending due task football_data_app.run_score_and_settlement_task
```

Check the Football worker logs to see task execution:
```bash
docker-compose logs -f celery_worker_football
```

## Alternative: Using Crontab Schedule

For more precise scheduling (e.g., only during specific hours):

1. In Django Admin, go to **Crontabs** (under DJANGO CELERY BEAT)

2. Create a new crontab:
   - **Minute**: `*/10` (every 10 minutes)
   - **Hour**: `6-23` (6 AM to 11 PM only)
   - **Day of week**: `*` (every day)
   - **Day of month**: `*`
   - **Month of year**: `*`

3. When creating the Periodic Task, select **Crontab** instead of Interval

## Task Routing

All scheduled tasks are automatically routed based on the configuration in `celery.py`:

- **Football tasks** → `football_data` queue → Football worker
- **WhatsApp tasks** → `whatsapp` queue → WhatsApp worker

The routing happens automatically based on the task module path.

## Monitoring

### Check Active Schedules
```bash
# Via Django Admin
# Go to: Periodic Tasks > View all tasks

# Via Database
docker exec -it whatsappcrm_db psql -U crm_user -d whatsapp_crm_dev \
  -c "SELECT name, task, enabled FROM django_celery_beat_periodictask;"
```

### Check Task Execution History
```bash
# Via Django Admin
# Go to: Task Results (if using django-celery-results)

# Via Logs
docker-compose logs --tail=100 celery_worker_football | grep "Task.*succeeded"
```

### Disable a Scheduled Task
1. Go to Django Admin → Periodic Tasks
2. Find the task
3. Uncheck **Enabled**
4. Click **Save**

## Troubleshooting

### Tasks Not Running

1. **Check Celery Beat is running**:
   ```bash
   docker-compose ps celery_beat
   ```

2. **Check Beat logs for errors**:
   ```bash
   docker-compose logs celery_beat | grep ERROR
   ```

3. **Verify task is registered**:
   ```bash
   docker exec -it whatsappcrm_celery_worker_football \
     celery -A whatsappcrm_backend.celery inspect registered | grep football_data_app
   ```

4. **Check task is enabled in admin**:
   - Go to Periodic Tasks in admin
   - Ensure **Enabled** is checked

### Tasks Running on Wrong Worker

If football tasks appear on the WhatsApp worker:
1. Check `celery.py` task routing configuration
2. Verify the queue name in the periodic task matches the routing
3. Restart workers: `docker-compose restart celery_worker celery_worker_football`

### Too Many Tasks Executing

If tasks pile up:
1. Check worker concurrency settings
2. Review task execution time
3. Consider increasing worker count or concurrency
4. Adjust task schedule intervals

## Best Practices

1. **Start Conservative**: Begin with longer intervals (15-20 minutes) and adjust based on load
2. **Monitor Performance**: Watch worker logs and database load
3. **Use Crontabs for Precision**: Schedule intensive tasks during off-peak hours
4. **Enable One at a Time**: Enable tasks one by one to verify they work correctly
5. **Check Task Duration**: Ensure tasks complete before the next execution starts

## Example: Initial Setup Commands

After deploying, run these steps:

```bash
# 1. Ensure services are running
docker-compose up -d

# 2. Apply migrations (includes django-celery-beat tables)
docker-compose exec backend python manage.py migrate

# 3. Create superuser if needed
docker-compose exec backend python manage.py createsuperuser

# 4. Access admin and create periodic tasks as described above
echo "Go to http://your-domain/admin/ and set up periodic tasks"

# 5. Verify setup
docker-compose logs -f celery_beat
```

## Summary

- ✅ Celery Beat is already configured in docker-compose.yml
- ✅ django-celery-beat is installed and configured
- ⚠️ **Action Required**: You must manually create periodic tasks in Django Admin
- 📋 **Tasks to Schedule**:
  1. Football Data Update (every 10 minutes)
  2. Score and Settlement (every 5 minutes)

Once scheduled via admin, tasks will run automatically according to their intervals.
