# Migration Guide: The Odds API → APIFootball.com

This guide explains how to migrate from The Odds API to APIFootball.com in the WhatsApp CRM system.

## Overview

The football_data_app has been updated to use **APIFootball.com** as the primary data provider. This migration provides:

- ✅ More comprehensive football data coverage
- ✅ Better live score support  
- ✅ Enhanced odds information with multiple bookmakers
- ✅ More reliable API with better uptime
- ✅ Improved error handling and retry logic

## Pre-Migration Checklist

Before starting the migration, ensure you have:

- [ ] **Backup**: Full database backup
- [ ] **API Key**: Valid APIFootball.com API key
- [ ] **Access**: Admin access to Django admin panel
- [ ] **Downtime**: Planned maintenance window (recommended: 30-60 minutes)
- [ ] **Testing**: Staging environment for testing (recommended)

## Migration Steps

### Step 1: Obtain APIFootball.com API Key

1. Visit [APIFootball.com](https://apifootball.com/)
2. Sign up for an account
3. Subscribe to a plan that meets your needs:
   - **Free**: 1,000 requests/day (good for testing)
   - **Basic**: 10,000 requests/day
   - **Pro**: 100,000 requests/day
4. Copy your API key from the dashboard

### Step 2: Update Environment Variables

Add the APIFootball key to your `.env` file:

```env
# APIFootball.com configuration
API_FOOTBALL_KEY=your_apifootball_api_key_here

# Optional: Keep The Odds API key for fallback
THE_ODDS_API_KEY=your_theoddsapi_key_here
```

### Step 3: Pull Latest Code

```bash
cd /path/to/whatsappcrm
git pull origin main
```

### Step 4: Stop Services

```bash
# Stop all services
docker-compose down

# OR if running locally
sudo systemctl stop celery-worker
sudo systemctl stop celery-beat
sudo systemctl stop gunicorn
```

### Step 5: Run Database Migrations

```bash
# Using Docker
docker-compose run backend python manage.py migrate football_data_app

# OR locally
cd whatsappcrm_backend
python manage.py migrate football_data_app
```

This will:
- Add new fields to existing models
- Update Configuration model with provider choices
- Add APIFootball-specific fields (country_id, league_season, etc.)

### Step 6: Configure APIFootball in Admin

1. Start the backend service:
   ```bash
   docker-compose up -d backend
   # OR
   python manage.py runserver
   ```

2. Log into Django admin: `http://localhost:8000/admin`

3. Navigate to **Football Data App > Configurations**

4. Create new configuration:
   - **Provider Name**: APIFootball
   - **Email**: your_email@example.com
   - **API Key**: your_apifootball_api_key
   - **Is Active**: ✓ (checked)

5. (Optional) Mark old "The Odds API" configuration as inactive

### Step 7: Initialize Leagues

Run the management command to fetch leagues from APIFootball:

```bash
# Using Docker
docker-compose exec backend python manage.py football_league_setup

# OR locally
python manage.py football_league_setup
```

This will:
- Fetch all available football leagues
- Create or update league records
- Preserve existing league data where possible

### Step 8: Update Celery Beat Schedule

Update your `celery.py` or Celery Beat configuration:

```python
# whatsappcrm_backend/whatsappcrm_backend/celery.py

from celery.schedules import crontab

app.conf.beat_schedule = {
    # Main data update pipeline (hourly)
    'fetch-football-data-hourly': {
        'task': 'football_data_app.run_apifootball_full_update',
        'schedule': crontab(minute=0),  # Every hour at :00
    },
    
    # Live scores and settlement (every 5 minutes)
    'fetch-live-scores': {
        'task': 'football_data_app.run_score_and_settlement_task',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    
    # Reconciliation for missed settlements (every 10 minutes)
    'reconcile-pending-bets': {
        'task': 'football_data_app.reconcile_and_settle_pending_items',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    },
}
```

### Step 9: Restart All Services

```bash
# Using Docker
docker-compose up -d

# OR locally
sudo systemctl start celery-worker
sudo systemctl start celery-beat
sudo systemctl start gunicorn
```

### Step 10: Verify Migration

1. **Check logs** for any errors:
   ```bash
   # Docker
   docker-compose logs -f backend
   docker-compose logs -f celery_worker
   
   # Local
   tail -f logs/django.log
   tail -f logs/celery_worker.log
   ```

2. **Verify data fetching**:
   - Check Django admin for new leagues
   - Verify fixtures are being created
   - Check that odds are being fetched

3. **Test betting flow**:
   - Create a test bet
   - Verify odds display correctly
   - Check settlement works properly

## Post-Migration

### Monitoring

Monitor the following for the first 24-48 hours:

1. **API Usage**: Check APIFootball dashboard for request counts
2. **Error Rates**: Monitor logs for API errors or failures
3. **Data Freshness**: Verify fixtures and odds are updating regularly
4. **Settlement**: Ensure bets are being settled correctly

### Optimization

After confirming everything works:

1. **Adjust Update Frequency**: Fine-tune Celery Beat schedules based on your needs
2. **Deactivate Old Provider**: In Django admin, set The Odds API configuration to inactive
3. **Clean Up**: Remove old unused data if desired

### Troubleshooting

#### No leagues appearing

```bash
# Check API key
docker-compose exec backend python manage.py shell
>>> from football_data_app.apifootball_client import APIFootballClient
>>> client = APIFootballClient()
>>> leagues = client.get_leagues()
>>> print(f"Found {len(leagues)} leagues")
```

#### Tasks not running

```bash
# Check Celery workers
docker-compose exec celery_worker celery -A whatsappcrm_backend inspect active

# Check Beat schedule
docker-compose exec celery_beat celery -A whatsappcrm_backend inspect scheduled
```

#### Data not updating

1. Check if leagues are marked as `active` in admin
2. Verify API key is valid and has quota remaining
3. Check logs for specific error messages

## Rollback Plan

If you need to rollback to The Odds API:

### Option 1: Quick Rollback (No Code Changes)

1. In Django admin, deactivate APIFootball configuration
2. Activate The Odds API configuration
3. Update `.env` to prioritize THE_ODDS_API_KEY
4. Restart services

### Option 2: Full Rollback (Restore Old Code)

1. Stop all services
2. Checkout previous commit:
   ```bash
   git checkout <previous-commit-sha>
   ```
3. Restore database from backup
4. Start services

## Data Preservation

### Existing Data

The migration preserves:
- ✅ All existing leagues (matched by api_id)
- ✅ All existing fixtures
- ✅ All existing bets and tickets
- ✅ All historical data

### Data Mapping

| The Odds API | APIFootball.com | Notes |
|--------------|-----------------|-------|
| sport_key | league_id | Primary identifier |
| event_id | match_id | Fixture identifier |
| home_team | match_hometeam_name | Team names |
| away_team | match_awayteam_name | Team names |
| commence_time | match_date + match_time | Match datetime |

## API Rate Limits

Be aware of rate limits to avoid service disruption:

### APIFootball.com

| Plan | Requests/Day | Requests/Minute |
|------|--------------|-----------------|
| Free | 1,000 | 30 |
| Basic | 10,000 | 100 |
| Pro | 100,000 | 300 |

### Recommended Update Frequencies

Based on typical usage:

| Task | Frequency | Requests/Day |
|------|-----------|--------------|
| League Updates | Daily | ~1 |
| Fixture Updates | Hourly | ~24 |
| Odds Updates | Hourly | ~24-240 (depending on active fixtures) |
| Live Scores | Every 5 min | ~288 |

**Total Estimate**: 300-600 requests/day (Basic plan recommended)

## Support

### Documentation

- [APIFootball Documentation](https://apifootball.com/documentation/)
- [Integration Guide](./whatsappcrm_backend/football_data_app/README_APIFOOTBALL.md)
- [Django Admin Guide](./docs/admin-guide.md)

### Getting Help

1. Check logs first: `docker-compose logs -f backend celery_worker`
2. Review [Troubleshooting Guide](./whatsappcrm_backend/football_data_app/README_APIFOOTBALL.md#troubleshooting)
3. Check GitHub issues for similar problems
4. Contact APIFootball support for API-specific issues

## Appendix

### Configuration Reference

Full list of settings in `settings.py`:

```python
# APIFootball Configuration
API_FOOTBALL_KEY = os.environ.get('API_FOOTBALL_KEY')
APIFOOTBALL_LEAD_TIME_DAYS = 7
APIFOOTBALL_EVENT_DISCOVERY_STALENESS_HOURS = 6
APIFOOTBALL_UPCOMING_STALENESS_MINUTES = 60
APIFOOTBALL_ASSUMED_COMPLETION_MINUTES = 120
APIFOOTBALL_MAX_EVENT_RETRIES = 3
APIFOOTBALL_EVENT_RETRY_DELAY = 300
```

### Database Schema Changes

New fields added:

**League model:**
- `country_id` (CharField, nullable)
- `country_name` (CharField, nullable)
- `league_season` (CharField, nullable)

**Team model:**
- `badge_url` (URLField, nullable)

**Configuration model:**
- `is_active` (BooleanField, default=True)
- `created_at` (DateTimeField, auto_now_add)
- `updated_at` (DateTimeField, auto_now)
- `provider_name` choices updated

### Task Name Mappings

For backward compatibility:

| Old Task Name | New Task Name |
|--------------|---------------|
| `run_the_odds_api_full_update` | `run_apifootball_full_update_task` |
| `fetch_and_update_leagues_task` | (same) |
| `fetch_events_for_league_task` | (same) |
| `fetch_odds_for_single_event_task` | (same) |

All old task names still work as aliases.
