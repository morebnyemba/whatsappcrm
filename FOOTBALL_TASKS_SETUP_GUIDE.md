# Football Tasks Setup Guide

## ⚠️ Important: API Provider Clarification

**PR #56** added support for the **new API-Football v3** (api-football.com with dash) as the recommended provider. **NEW**: Robust production-ready tasks are now available!

### Current Status:
- ✅ **New API Client Available**: `api_football_v3_client.py` for API-Football v3 (api-football.com)
- ✅ **New Tasks Created**: `tasks_api_football_v3.py` provides full-featured scheduled tasks
- ⚙️ **Legacy Tasks Still Available**: Tasks in `tasks_apifootball.py` still use the legacy provider
- 📖 **This Guide**: Documents **both** the new API-Football v3 tasks and legacy tasks

### Your Options:

1. **Use New API-Football v3 Tasks (RECOMMENDED)** - Production-ready tasks for the new API
2. **Use Legacy Tasks** - Still works but uses older APIFootball.com API
3. **Use API-Football v3 Client Directly** - For custom implementations

For complete information about the new API-Football v3, see [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md).

---

## Overview

This guide answers the question: **"Where are the tasks and how do I schedule the tasks for football from implementation #56 and what's the first time command?"**

This comprehensive guide covers:
1. Where the football tasks are located (currently using legacy provider)
2. The first-time setup command you need to run
3. How to schedule tasks for automatic execution
4. How to use the new API-Football v3 client
5. Verification and troubleshooting

---

## Quick Answer (Legacy Tasks)

### 🎯 First Time Command (REQUIRED)

Before scheduling any tasks, you **MUST** run this command to initialize football leagues:

```bash
# From outside the container
docker-compose exec backend python manage.py football_league_setup
```

**Why?** This command fetches available football leagues from APIFootball.com and populates your database. Without this, scheduled tasks will report "0 active leagues" and no betting data will be available.

### 📍 Where Are the Tasks?

The football tasks are located in:
- **File**: `/whatsappcrm_backend/football_data_app/tasks_apifootball.py`
- **Main Task Names** (for scheduling in Django Admin):
  1. `football_data_app.run_apifootball_full_update`
  2. `football_data_app.run_score_and_settlement_task`

---

## Using New API-Football v3 (Recommended)

✅ **NEW**: Robust production-ready tasks are now available for API-Football v3!

The new tasks are located in `/whatsappcrm_backend/football_data_app/tasks_api_football_v3.py` and provide full feature parity with the legacy tasks.

### Step 1: Get API-Football v3 API Key

1. Visit [api-football.com](https://www.api-football.com/)
2. Sign up for an account
3. Get your API key from the dashboard
4. Note: This is a **different service** from apifootball.com (without dash)

### Step 2: Configure API-Football v3

You have two options for configuration:

**Option A: Via Django Admin (Recommended)**

1. Go to http://your-domain/admin/
2. Navigate to **Football Data App > Configurations**
3. Add a new Configuration:
   - **Provider Name**: `API-Football` (with dash)
   - **API Key**: `your_api_key_here`
   - **Current Season**: `2024` (or the current season year)
   - **Email**: Your contact email
   - **Is Active**: ✓ (checked)
4. Click **Save**

**Option B: Via Environment Variables**

Add to your `.env` file:

```env
API_FOOTBALL_V3_KEY=your_api_key_here
API_FOOTBALL_V3_CURRENT_SEASON=2024
```

**Note**: Django Admin configuration takes priority over environment variables. If you configure via Django Admin, the system will use those values instead of environment variables.

### Step 3: Apply Database Migration

After configuring the API key and season, apply the database migration to add the `current_season` field:

```bash
# Create the migration
docker-compose exec backend python manage.py makemigrations football_data_app

# Apply the migration
docker-compose exec backend python manage.py migrate football_data_app
```

### Step 4: Initialize Leagues

Run the setup command to populate leagues from API-Football v3:

```bash
# From outside the container (recommended)
docker-compose exec backend python manage.py football_league_setup_v3

# From inside the container
python manage.py football_league_setup_v3
```

**What this does:**
- Fetches leagues from API-Football v3 (api-football.com)
- Creates leagues with `v3_` prefix to distinguish from legacy leagues
- Safe to run multiple times (uses update_or_create)

**Expected output:**
```
Starting the football league setup process with API-Football v3 (api-football.com)...
Starting football leagues setup with API-Football v3 (api-football.com).
Football leagues setup finished. Created: 150, Updated: 0.
Football league setup process completed.
```

### Step 5: Schedule the New Tasks in Django Admin

#### Task 1: Football Data Update (API-Football v3)

1. Go to Django Admin → **DJANGO CELERY BEAT > Periodic Tasks**
2. Click **"Add Periodic Task"**
3. Fill in:
   - **Name**: `Football Data Update (API-Football v3)`
   - **Task (registered)**: `football_data_app.run_api_football_v3_full_update`
   - **Interval**: Create new interval - Every `10` Minutes
   - **Queue**: `football_data`
   - **Enabled**: ✓ (checked)
4. Click **Save**

**What this task does:**
- Fetches leagues from API-Football v3
- Fetches upcoming fixtures (next 7 days)
- Fetches betting odds from multiple bookmakers
- Updates fixture and odds data automatically

#### Task 2: Score and Settlement (API-Football v3)

1. Click **"Add Periodic Task"** again
2. Fill in:
   - **Name**: `Score and Settlement (API-Football v3)`
   - **Task (registered)**: `football_data_app.run_score_and_settlement_v3_task`
   - **Interval**: Create new interval - Every `5` Minutes
   - **Queue**: `football_data`
   - **Enabled**: ✓ (checked)
3. Click **Save**

**What this task does:**
- Fetches live scores and finished matches
- Updates fixture statuses (LIVE → FINISHED)
- Settles bets and tickets automatically
- Sends WhatsApp notifications to customers

### Step 6: Verify Tasks Are Running

Check the logs to see tasks executing:

```bash
# View Celery Beat logs (scheduler)
docker-compose logs -f celery_beat

# View Football Worker logs (task execution)
docker-compose logs -f celery_cpu_worker

# View last 100 lines
docker-compose logs --tail=100 celery_cpu_worker
```

**Look for entries like:**
```
[INFO] TASK START: run_api_football_v3_full_update_task
[INFO] Received 150 leagues from API-Football v3 API
[INFO] Processing 25 fixtures for league Premier League...
[INFO] TASK END: run_api_football_v3_full_update_task - SUCCESS
```

### Using the Client Directly (Advanced)

You can also use the API-Football v3 client directly in your code:

```python
from football_data_app.api_football_v3_client import APIFootballV3Client

# Initialize client
client = APIFootballV3Client()

# Get leagues
leagues = client.get_leagues()

# Get fixtures for a league
fixtures = client.get_fixtures(league_id=39, season=2024)  # Premier League

# Get odds
odds = client.get_odds(fixture_id=12345)

# Get live scores
live_scores = client.get_live_fixtures()
```

For complete documentation on the new API-Football v3 client, see [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md).

---

## Complete Setup Workflow (Legacy Tasks)

### Step 1: Configure API Key

Ensure you have an APIFootball.com API key configured:

**Option A: Via Environment Variable (.env file)**
```bash
API_FOOTBALL_KEY=your_api_key_here
```

**Option B: Via Django Admin**
1. Go to http://your-domain/admin/
2. Navigate to **Football Data App > Configurations**
3. Add a new Configuration:
   - Provider Name: `APIFootball`
   - API Key: `your_api_key_here`
   - Is Active: ✓ (checked)

**Get your API key**: https://apifootball.com/

---

### Step 2: Run First-Time Setup Command

This is the **critical first step** that initializes your football leagues:

```bash
# Option 1: From outside the container (recommended)
docker-compose exec backend python manage.py football_league_setup

# Option 2: From inside the container
docker exec -it whatsappcrm_backend python manage.py football_league_setup
```

**What this command does:**
- Fetches all available football leagues from APIFootball.com
- Populates the `League` table in your database
- Marks leagues as active by default
- Is safe to run multiple times (uses update_or_create)

**Expected output:**
```
Starting the football league setup process with APIFootball.com...
Starting football leagues setup with APIFootball.com.
Football leagues setup finished. Created: 150, Updated: 0.
Football league setup process completed.
```

---

### Step 3: Verify Setup

Check that leagues were initialized successfully:

```bash
# Quick check - count active leagues
docker-compose exec backend python manage.py shell -c "from football_data_app.models import League; print(f'Active leagues: {League.objects.filter(active=True).count()}')"

# Comprehensive check - runs all system checks
docker-compose exec backend python manage.py check_football_setup
```

**Expected output:**
```
Active leagues: 150
```

If you see `Active leagues: 0`, re-run the `football_league_setup` command and check your API key configuration.

---

### Step 4: Schedule Periodic Tasks in Django Admin

Now that leagues are initialized, schedule the tasks to run automatically:

#### A. Access Django Admin

1. Navigate to: `http://your-domain/admin/`
2. Log in with your superuser credentials
3. Go to **DJANGO CELERY BEAT > Periodic Tasks**

#### B. Schedule Task 1: Football Data Update

This task fetches fixtures, leagues, and odds from APIFootball.com.

1. Click **"Add Periodic Task"**
2. Fill in the following:
   - **Name**: `Football Data Update`
   - **Task (registered)**: `football_data_app.run_apifootball_full_update`
   - **Interval**: Click the green + to create new interval
     - Every: `10`
     - Period: `Minutes`
   - **Queue**: `football_data` (important for routing to the correct worker)
   - **Enabled**: ✓ (checked)
3. Click **Save**

**Recommended Schedule**: Every 10-15 minutes during active hours

#### C. Schedule Task 2: Score and Settlement

This task fetches match scores and settles bets/tickets.

1. Click **"Add Periodic Task"**
2. Fill in the following:
   - **Name**: `Score and Settlement`
   - **Task (registered)**: `football_data_app.run_score_and_settlement_task`
   - **Interval**: Click the green + to create new interval
     - Every: `5`
     - Period: `Minutes`
   - **Queue**: `football_data` (important for routing to the correct worker)
   - **Enabled**: ✓ (checked)
3. Click **Save**

**Recommended Schedule**: Every 5-10 minutes during match hours

---

### Step 5: Verify Tasks Are Running

#### Check Celery Beat Logs (Scheduler)

The Celery Beat scheduler should show tasks being dispatched:

```bash
docker-compose logs -f celery_beat
```

**Look for entries like:**
```
[INFO] Scheduler: Sending due task football_data_app.run_apifootball_full_update
[INFO] Scheduler: Sending due task football_data_app.run_score_and_settlement_task
```

#### Check Football Worker Logs (Task Execution)

The football worker executes the tasks:

```bash
# View real-time logs
docker-compose logs -f celery_cpu_worker

# View last 100 lines
docker-compose logs --tail=100 celery_cpu_worker
```

**Look for entries like:**
```
[INFO] TASK START: run_apifootball_full_update_task
[INFO] Found 150 active leagues
[INFO] Processing fixtures for league Premier League...
[INFO] TASK END: run_apifootball_full_update_task - SUCCESS
```

#### Check Task Status in Django Admin

1. Go to **DJANGO CELERY BEAT > Periodic Tasks**
2. Find your tasks in the list
3. Check the **Last Run At** column - it should update after each execution
4. Click on a task to see detailed execution history

---

## Task Details (Legacy APIFootball.com)

### Task 1: run_apifootball_full_update

**Full Task Path**: `football_data_app.tasks_apifootball.run_apifootball_full_update_task`  
**Scheduling Name**: `football_data_app.run_apifootball_full_update`  
**Queue**: `football_data`  
**Worker**: `celery_cpu_worker` (prefork pool, 4 workers)

**What it does:**
1. Fetches all available leagues from APIFootball.com
2. For each league:
   - Fetches upcoming fixtures (next 7 days by default)
   - Creates/updates fixture records
   - Creates/updates team records
3. For each fixture:
   - Fetches betting odds from multiple bookmakers
   - Creates/updates market and outcome records

**Configuration (in settings.py or .env):**
- `APIFOOTBALL_LEAD_TIME_DAYS`: How many days ahead to fetch fixtures (default: 7)
- `APIFOOTBALL_UPCOMING_STALENESS_MINUTES`: How old odds can be before refetching (default: 60)

**Expected behavior:**
- On first run: Fetches all fixtures and odds (may take 5-10 minutes)
- On subsequent runs: Only updates stale fixtures and odds (faster)

### Task 2: run_score_and_settlement_task

**Full Task Path**: `football_data_app.tasks_apifootball.run_score_and_settlement_task`  
**Scheduling Name**: `football_data_app.run_score_and_settlement_task`  
**Queue**: `football_data`  
**Worker**: `celery_cpu_worker` (prefork pool, 4 workers)

**What it does:**
1. Fetches live scores from APIFootball.com
2. Fetches recently finished matches (past 2 days)
3. Updates fixture scores and statuses (LIVE → FINISHED)
4. When a fixture finishes:
   - Settles market outcomes (WON/LOST/PUSH)
   - Settles individual bets based on outcomes
   - Settles bet tickets (multi-bet slips)
   - Credits/debits customer wallets
   - Sends WhatsApp notifications to customers

**Expected behavior:**
- During match hours: Frequently updates live scores
- When matches finish: Automatically settles all related bets
- Sends notifications to affected customers

---

## Alternative Task Scheduling (Crontab)

For more precise scheduling (e.g., only during specific hours):

### Create a Crontab Schedule

1. In Django Admin, go to **DJANGO CELERY BEAT > Crontabs**
2. Click **"Add Crontab"**
3. Configure the schedule:
   - **Minute**: `*/10` (every 10 minutes)
   - **Hour**: `6-23` (6 AM to 11 PM only)
   - **Day of week**: `*` (every day)
   - **Day of month**: `*`
   - **Month of year**: `*`
4. Click **Save**

### Use Crontab in Periodic Task

When creating/editing a periodic task:
- Instead of selecting **Interval**, select your **Crontab**
- Leave Interval empty

This allows you to run tasks only during specific hours, reducing API usage during off-peak times.

---

## Task Routing Architecture

The system uses **two separate Celery workers** for better performance:

### WhatsApp Worker (`celery_io_worker`)
- **Queue**: `whatsapp` (default)
- **Pool**: gevent (I/O optimized)
- **Concurrency**: 100
- **Handles**: Messaging, conversations, payments, referrals

### Football Data Worker (`celery_cpu_worker`)
- **Queue**: `football_data`
- **Pool**: prefork (CPU optimized)
- **Concurrency**: 4
- **Handles**: Fixtures, odds, scores, settlements

**Important**: Always set the **Queue** to `football_data` when creating football-related periodic tasks in Django Admin.

---

## Troubleshooting

### Issue: "Found 0 active leagues" in Logs

**Cause**: The `football_league_setup` command hasn't been run, or it failed.

**Solution**:
1. Run: `docker-compose exec backend python manage.py football_league_setup`
2. Check your API key configuration
3. Verify API connectivity: `docker-compose exec backend python manage.py check_football_setup`

### Issue: Tasks Not Running

**Check 1: Celery Beat is Running**
```bash
docker-compose ps celery_beat
# Should show "Up" status
```

**Check 2: Football Worker is Running**
```bash
docker-compose ps celery_cpu_worker
# Should show "Up" status
```

**Check 3: Tasks are Enabled in Admin**
- Go to Django Admin > Periodic Tasks
- Ensure **Enabled** is checked

**Check 4: Task is Registered**
```bash
docker exec -it whatsappcrm_celery_cpu_worker celery -A whatsappcrm_backend inspect registered | grep football_data_app
```

**Expected output:**
```
football_data_app.run_apifootball_full_update
football_data_app.run_score_and_settlement_task
```

### Issue: Tasks Running on Wrong Worker

If football tasks appear on the WhatsApp worker logs:
1. Check `celery.py` task routing configuration
2. Verify the **Queue** field in the periodic task is set to `football_data`
3. Restart workers: `docker-compose restart celery_io_worker celery_cpu_worker`

### Issue: API Authentication Errors

**Symptoms**: Logs show "invalid API key" or "authentication failed"

**Solutions**:
1. Verify API key in `.env` file or Django admin
2. Check your subscription at: https://apifootball.com/dashboard
3. Ensure your API key has not expired
4. Test API connectivity: `docker-compose exec backend python manage.py check_football_setup`

### Issue: No Fixtures Being Fetched

**Possible causes**:
1. No active leagues in database → Run `football_league_setup`
2. API rate limit exceeded → Check your APIFootball.com dashboard
3. API subscription doesn't include required endpoints → Upgrade plan

**Debug**:
```bash
# Check league count
docker-compose exec backend python manage.py shell -c "from football_data_app.models import League; print(f'Active: {League.objects.filter(active=True).count()}')"

# Check fixture count
docker-compose exec backend python manage.py shell -c "from football_data_app.models import FootballFixture; print(f'Fixtures: {FootballFixture.objects.count()}')"

# Run comprehensive check
docker-compose exec backend python manage.py check_football_setup
```

---

## Monitoring and Maintenance

### View Task Execution History

**Via Django Admin:**
1. Go to **DJANGO CELERY BEAT > Periodic Tasks**
2. Click on a task name
3. View **Last Run At**, **Total Run Count**

**Via Logs:**
```bash
# View last 100 successful task completions
docker-compose logs --tail=100 celery_cpu_worker | grep "TASK END.*SUCCESS"

# View task errors
docker-compose logs celery_cpu_worker | grep ERROR
```

### Check Active Leagues

```bash
docker-compose exec backend python manage.py shell -c "
from football_data_app.models import League
leagues = League.objects.filter(active=True)
for league in leagues[:10]:
    print(f'{league.name} ({league.country_name}) - API ID: {league.api_id}')
"
```

### Check Recent Fixtures

```bash
docker-compose exec backend python manage.py shell -c "
from football_data_app.models import FootballFixture
from django.utils import timezone
fixtures = FootballFixture.objects.filter(
    match_date__gte=timezone.now()
).order_by('match_date')[:10]
for f in fixtures:
    print(f'{f.match_date} | {f.home_team.name} vs {f.away_team.name}')
"
```

### Disable a Scheduled Task

1. Go to Django Admin → **Periodic Tasks**
2. Find the task you want to disable
3. Uncheck **Enabled**
4. Click **Save**

The task will stop being scheduled but remains configured for future use.

---

## Best Practices

1. **Start Conservative**: Begin with longer intervals (15-20 minutes) and adjust based on load
2. **Monitor Performance**: Watch worker logs and database load during initial runs
3. **Use Crontabs for Precision**: Schedule intensive tasks during off-peak hours
4. **Enable One at a Time**: Enable tasks one by one to verify they work correctly
5. **Check Task Duration**: Ensure tasks complete before the next execution starts
6. **Monitor API Usage**: Check your APIFootball.com dashboard for quota usage
7. **Regular Maintenance**: Periodically check task execution logs for errors

---

## Summary Checklist

### For Legacy APIFootball.com Tasks:
- [ ] Configure APIFootball.com API key in `.env` or Django admin (provider: `APIFootball`)
- [ ] Run first-time setup: `docker-compose exec backend python manage.py football_league_setup`
- [ ] Verify leagues were initialized: Check admin or run `check_football_setup`
- [ ] Ensure Celery workers are running: `docker-compose ps`
- [ ] Create periodic task for **Football Data Update** (every 10 mins)
- [ ] Create periodic task for **Score and Settlement** (every 5 mins)
- [ ] Verify tasks are enabled in Django admin
- [ ] Monitor logs to ensure tasks are executing: `docker-compose logs -f celery_cpu_worker`
- [ ] Check that fixtures and odds are being populated in the database

### For New API-Football v3 Tasks (RECOMMENDED):
- [ ] Get API key from [api-football.com](https://www.api-football.com/)
- [ ] Configure via Django Admin (recommended):
  - Go to **Football Data App > Configurations**
  - Add: Provider=`API-Football`, API Key, Current Season=`2024`, Is Active=✓
- [ ] OR configure in `.env`: `API_FOOTBALL_V3_KEY=your_key` and `API_FOOTBALL_V3_CURRENT_SEASON=2024`
- [ ] Apply database migration: `docker-compose exec backend python manage.py makemigrations football_data_app && docker-compose exec backend python manage.py migrate football_data_app`
- [ ] Run setup command: `docker-compose exec backend python manage.py football_league_setup_v3`
- [ ] Verify leagues initialized (should have `v3_` prefix in api_id)
- [ ] Ensure Celery workers are running: `docker-compose ps`
- [ ] Create periodic task: **Football Data Update (API-Football v3)** (every 10 mins)
  - Task name: `football_data_app.run_api_football_v3_full_update`
  - Queue: `football_data`
- [ ] Create periodic task: **Score and Settlement (API-Football v3)** (every 5 mins)
  - Task name: `football_data_app.run_score_and_settlement_v3_task`
  - Queue: `football_data`
- [ ] Verify tasks are enabled in Django admin
- [ ] Monitor logs: `docker-compose logs -f celery_cpu_worker`
- [ ] Check fixtures and odds are being populated
- [ ] Review [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md) for complete documentation

---

## Related Documentation

- [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md) - **New API-Football v3 complete guide**
- [SCHEDULED_TASKS_SETUP.md](SCHEDULED_TASKS_SETUP.md) - Detailed periodic task configuration
- [GETTING_STARTED.md](GETTING_STARTED.md) - Complete deployment guide
- [README.md](README.md) - Project overview and architecture
- [CELERY_WORKER_SETUP.md](CELERY_WORKER_SETUP.md) - Worker configuration details
- [LEAGUE_INITIALIZATION_FIX.md](LEAGUE_INITIALIZATION_FIX.md) - League setup troubleshooting

---

## Support

For additional help:

**New API-Football v3 Tasks:**
1. Check task logs: `docker-compose logs celery_cpu_worker celery_beat`
2. Verify leagues have `v3_` prefix: Check Django admin → Leagues
3. Run setup command if needed: `docker-compose exec backend python manage.py football_league_setup_v3`
4. See comprehensive guide: [API_FOOTBALL_V3_INTEGRATION.md](API_FOOTBALL_V3_INTEGRATION.md)
5. Check API-Football v3 documentation: https://www.api-football.com/documentation-v3
6. Visit API dashboard: https://www.api-football.com/account
7. Monitor API usage and remaining calls on your dashboard

**Legacy APIFootball.com:**
1. Check task logs: `docker-compose logs celery_cpu_worker celery_beat`
2. Run system check: `docker-compose exec backend python manage.py check_football_setup`
3. Review the [SCHEDULED_TASKS_SETUP.md](SCHEDULED_TASKS_SETUP.md) guide
4. Check APIFootball.com API documentation: https://apifootball.com/documentation/

**Remember**: 
- **New v3 tasks** use **API-Football v3** (with dash) at api-football.com - Task names: `run_api_football_v3_full_update`, `run_score_and_settlement_v3_task`
- **Legacy tasks** use **APIFootball.com** (without dash) - Task names: `run_apifootball_full_update`, `run_score_and_settlement_task`
- These are **two different services** with different API keys and task names!
- Leagues from v3 have `v3_` prefix in their `api_id` field
