# APIFootball.com Integration Guide

This document explains the integration with APIFootball.com and how to use it in the WhatsApp CRM system.

## Overview

The football_data_app now uses **APIFootball.com** as the primary data provider instead of The Odds API. This change provides:

- ✅ More comprehensive football data coverage
- ✅ Better live score support
- ✅ Enhanced odds information
- ✅ More reliable API with better error handling
- ✅ Support for multiple leagues and competitions worldwide

## Getting Started

### 1. Obtain an API Key

1. Visit [APIFootball.com](https://apifootball.com/)
2. Sign up for an account
3. Choose a plan that suits your needs
4. Copy your API key from the dashboard

### 2. Configure the API Key

You can configure the API key in two ways:

#### Option A: Environment Variable (Recommended)

Add to your `.env` file:

```env
API_FOOTBALL_KEY=your_api_key_here
```

#### Option B: Database Configuration

1. Log into the Django admin panel
2. Navigate to **Football Data App > Configurations**
3. Click "Add Configuration"
4. Fill in:
   - **Provider Name**: APIFootball
   - **Email**: Your contact email
   - **API Key**: Your APIFootball.com API key
   - **Is Active**: ✓ (checked)
5. Save

### 3. Run Initial Setup

Run the management command to fetch leagues:

```bash
python manage.py football_league_setup
```

This will:
- Fetch all available football leagues from APIFootball
- Populate your database with league information
- Set up teams and fixtures

## Architecture

### Components

1. **apifootball_client.py**
   - Robust HTTP client for APIFootball.com
   - Handles authentication, retries, and error handling
   - Provides methods for all major endpoints

2. **tasks_apifootball.py**
   - Celery tasks for data fetching and processing
   - Handles leagues, fixtures, odds, and scores
   - Implements settlement logic for betting

3. **models.py**
   - Enhanced with APIFootball-specific fields
   - Supports country information, seasons, badges
   - Maintains backward compatibility

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Celery Beat Scheduler                     │
│                  (Triggers periodic tasks)                   │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│         run_apifootball_full_update_task                     │
│              (Main pipeline coordinator)                     │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┴────────────────────┐
        │                                         │
        ▼                                         ▼
┌──────────────────┐                    ┌──────────────────┐
│  Fetch Leagues   │                    │  Fetch Scores    │
│  (Daily)         │                    │  (Every 5 min)   │
└────────┬─────────┘                    └────────┬─────────┘
         │                                       │
         ▼                                       ▼
┌──────────────────┐                    ┌──────────────────┐
│  Fetch Fixtures  │                    │ Update Fixtures  │
│  (Hourly)        │                    │ Settle Bets      │
└────────┬─────────┘                    └──────────────────┘
         │
         ▼
┌──────────────────┐
│   Fetch Odds     │
│  (Hourly)        │
└──────────────────┘
```

## Available Tasks

### Main Pipeline Tasks

#### `run_apifootball_full_update_task()`
Main entry point for the full data update pipeline. This should be scheduled to run periodically (e.g., hourly).

```python
from football_data_app.tasks import run_apifootball_full_update_task
run_apifootball_full_update_task.delay()
```

#### `fetch_and_update_leagues_task()`
Fetches all available leagues from APIFootball and updates the database.

#### `fetch_events_for_league_task(league_id)`
Fetches upcoming fixtures for a specific league.

#### `fetch_odds_for_single_event_task(fixture_id)`
Fetches odds for a single fixture.

### Score and Settlement Tasks

#### `run_score_and_settlement_task()`
Fetches live scores and updates fixture statuses. Should run frequently (e.g., every 5 minutes).

```python
from football_data_app.tasks import run_score_and_settlement_task
run_score_and_settlement_task.delay()
```

#### `reconcile_and_settle_pending_items_task()`
Periodic task to find and settle any bets that may have been missed. Should run every 10-15 minutes.

## Configuration Parameters

Add these to your `settings.py` to customize behavior:

```python
# How many days ahead to fetch fixtures
APIFOOTBALL_LEAD_TIME_DAYS = 7

# Hours before refetching events
APIFOOTBALL_EVENT_DISCOVERY_STALENESS_HOURS = 6

# Minutes before refetching odds
APIFOOTBALL_UPCOMING_STALENESS_MINUTES = 60

# Minutes after scheduled start to assume match completion
APIFOOTBALL_ASSUMED_COMPLETION_MINUTES = 120
```

## Celery Beat Schedule Example

Add to your `celery.py`:

```python
from celery.schedules import crontab

app.conf.beat_schedule = {
    'fetch-football-data-hourly': {
        'task': 'football_data_app.run_apifootball_full_update',
        'schedule': crontab(minute=0),  # Every hour
    },
    'fetch-live-scores': {
        'task': 'football_data_app.run_score_and_settlement_task',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'reconcile-pending-bets': {
        'task': 'football_data_app.reconcile_and_settle_pending_items',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    },
}
```

## API Endpoints Used

The client uses the following APIFootball.com endpoints:

| Endpoint | Purpose | Frequency |
|----------|---------|-----------|
| `get_leagues` | Fetch all leagues | Daily |
| `get_events` | Fetch fixtures | Hourly |
| `get_odds` | Fetch betting odds | Hourly |
| `get_events?match_live=1` | Fetch live scores | Every 5 min |

## Error Handling

The client implements robust error handling:

1. **Retry Logic**: Automatically retries failed requests up to 3 times
2. **Rate Limiting**: Respects API rate limits with exponential backoff
3. **Logging**: Comprehensive logging for debugging
4. **Graceful Degradation**: Continues operation even if some requests fail

## Monitoring

Monitor the following logs for issues:

```bash
# View APIFootball client logs
tail -f logs/apifootball_client.log

# View task execution logs
tail -f logs/celery_worker.log

# Check for errors
grep ERROR logs/*.log
```

## Troubleshooting

### No data being fetched

1. **Check API key**: Verify the key is correct in `.env` or database
2. **Check logs**: Look for authentication errors
3. **Verify leagues**: Ensure leagues are marked as active in admin
4. **Check Celery**: Ensure Celery workers are running

```bash
# Check Celery status
celery -A whatsappcrm_backend inspect active
```

### Odds not updating

1. **Check last_odds_update**: In admin, check fixture's last update time
2. **Verify API quota**: Check if you've hit your API limit
3. **Check logs**: Look for specific fixture errors

### Scores not updating

1. **Verify fixture status**: Check if fixtures are marked as LIVE or SCHEDULED
2. **Check match dates**: Ensure dates are in the future or recent past
3. **Run manual score fetch**:

```bash
python manage.py shell
>>> from football_data_app.tasks import run_score_and_settlement_task
>>> run_score_and_settlement_task.delay()
```

## Migration from The Odds API

If you're migrating from The Odds API:

1. **Backup database**: Always backup before migration
2. **Update Configuration**: Create new APIFootball configuration
3. **Keep old data**: Old fixtures and bets remain intact
4. **Run new setup**: Execute `football_league_setup` command
5. **Update schedules**: Update Celery Beat schedules to use new tasks

The old The Odds API client is preserved in `tasks_theoddsapi_backup.py` for reference.

## Support

For issues with:
- **APIFootball API**: Visit [APIFootball Documentation](https://apifootball.com/documentation/)
- **Integration**: Check logs and GitHub issues
- **Betting Logic**: Review `utils.py` settlement functions

## API Limits

Be aware of your plan's API limits:

| Plan | Requests/Day | Requests/Minute |
|------|--------------|-----------------|
| Free | 1,000 | 30 |
| Basic | 10,000 | 100 |
| Pro | 100,000 | 300 |

Monitor usage to avoid hitting limits during peak times.

## Best Practices

1. **Cache wisely**: Don't fetch data more frequently than it changes
2. **Stagger requests**: Use jitter in tasks to avoid request bursts
3. **Monitor quotas**: Keep track of your API usage
4. **Handle failures**: Always have fallback mechanisms
5. **Log everything**: Comprehensive logging helps debugging

## Security Notes

- Never commit API keys to version control
- Use environment variables for sensitive data
- Rotate keys periodically
- Monitor for unusual API usage patterns
- Restrict database access to necessary personnel only
