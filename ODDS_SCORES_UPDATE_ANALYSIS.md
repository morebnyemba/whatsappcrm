# Odds and Scores Update Analysis

## Issue Comment
> "What about the odds and scores they are not being updated?"

## Analysis Summary

After thoroughly analyzing the codebase against the APIFootball.com documentation, here are the findings:

## Current Implementation Status

### ✅ Odds Updates ARE Implemented

**Location:** `tasks_apifootball.py` - `_process_apifootball_odds_data()` function (lines 97-204)

**How it works:**
1. Fetches odds via `get_odds` API endpoint (uses `action=get_odds`)
2. For each fixture, DELETE old Market records (line 153-157)
3. CREATE new Market records with updated odds (line 161-167)
4. CREATE new MarketOutcome records with current odds values (line 172-202)
5. Updates `fixture.last_odds_update = timezone.now()` (line 598)

**Per APIFootball.com documentation:** https://apifootball.com/documentation/
- Endpoint: `action=get_odds`
- Returns: `odd_bookmakers` array with bookmaker odds data
- Fields captured: `odd_1` (home win), `odd_x` (draw), `odd_2` (away win)

**Implementation is CORRECT** ✓

### ✅ Scores Updates ARE Implemented

**Location:** `tasks_apifootball.py` - `fetch_scores_for_league_task()` function (lines 664-863)

**How it works:**
1. Fetches live scores via `get_live_scores()` (line 706)
2. Fetches finished matches via `get_finished_matches()` (lines 711-718)
3. For each match, updates:
   - `fixture.home_team_score` (line 779)
   - `fixture.away_team_score` (line 781)
   - `fixture.last_score_update = timezone.now()` (line 783)
   - `fixture.match_updated` from API (line 785)
   - `fixture.status` (LIVE/FINISHED) (lines 794, 801)

**Per APIFootball.com documentation:** https://apifootball.com/documentation/
- Endpoint: `action=get_events` with `match_live=1` for live scores
- Returns: `match_hometeam_score`, `match_awayteam_score`, `match_status`, `match_updated`
- All these fields ARE being captured and stored

**Implementation is CORRECT** ✓

## Database Schema Review

### FootballFixture Model Fields

From `models.py` (lines 52-83):
```python
match_date = models.DateTimeField(null=True, blank=True)  # ✓ Captured
match_updated = models.DateTimeField(null=True, blank=True)  # ✓ Captured
status = models.CharField(...)  # ✓ Updated
home_team_score = models.IntegerField(null=True, blank=True)  # ✓ Updated
away_team_score = models.IntegerField(null=True, blank=True)  # ✓ Updated
last_odds_update = models.DateTimeField(null=True, blank=True)  # ✓ Tracked
last_score_update = models.DateTimeField(null=True, blank=True)  # ✓ Tracked
```

All necessary fields ARE present in the database model.

### Market Model Fields

From `models.py` (lines 114-132):
```python
last_updated_odds_api = models.DateTimeField(...)  # ✓ Tracked per market
```

The Market model tracks when each bookmaker's odds were last updated from the API.

## Potential Issues (Hypotheses)

Since the implementation appears correct, here are possible reasons for the reported issue:

### 1. Scheduled Tasks Not Running
**Hypothesis:** The Celery tasks may not be scheduled or running properly.

**Check:**
- Are Celery workers running? (`docker ps` should show celery_io_worker, celery_cpu_worker, celery_beat)
- Are scheduled tasks configured? (Check django_celery_beat.models.PeriodicTask in database)
- Are tasks being executed? (Check Celery logs)

**Solution:**
```bash
# Verify workers are running
docker-compose ps

# Check celery logs
docker-compose logs celery_cpu_worker
docker-compose logs celery_beat

# Manually trigger tasks to test
docker-compose exec backend python manage.py shell
>>> from football_data_app.tasks_apifootball import run_apifootball_full_update_task, run_score_and_settlement_task
>>> run_apifootball_full_update_task.delay()
>>> run_score_and_settlement_task.delay()
```

### 2. No Active Leagues
**Hypothesis:** No leagues are marked as `active=True` in the database.

**Check:**
```python
# In Django shell
from football_data_app.models import League
print(f"Active leagues: {League.objects.filter(active=True).count()}")
```

**Solution:**
- Run: `docker-compose exec backend python manage.py football_league_setup`
- Or manually activate leagues in Django admin

### 3. API Rate Limiting / Authentication Issues
**Hypothesis:** API requests are failing due to rate limits or invalid API key.

**Check:**
- Review logs for APIFootballException errors
- Check for HTTP 429 (rate limit) or 401 (auth) errors
- Verify API key is valid and has sufficient quota

**Solution:**
- Check API quota at https://apifootball.com/dashboard
- Verify API key configuration in database or environment variables

### 4. Old/Stale Data Being Displayed
**Hypothesis:** The data IS being updated, but cached or old data is being displayed to users.

**Check:**
- Check `last_odds_update` and `last_score_update` timestamps in database
- Compare with current time to see if updates are recent
- Check if frontend or API is caching responses

**Solution:**
```sql
-- Check recent updates in database
SELECT id, home_team_id, away_team_id, last_odds_update, last_score_update, match_updated
FROM football_data_app_footballfixture
ORDER BY last_odds_update DESC NULLS LAST
LIMIT 10;
```

### 5. Odds/Scores Not Available for Specific Matches
**Hypothesis:** The API may not return odds/scores for all matches.

**Check:**
- Some leagues or matches may not have odds available
- Some matches may not have live score updates
- The API plan may have restrictions

**Solution:**
- Check API response to see if odds/scores are actually returned
- Verify the league/match is supported by the API
- Check the logs for "No odds data returned" messages

## Verification Steps

### Step 1: Verify Database State
```bash
docker-compose exec backend python manage.py shell
```

```python
from football_data_app.models import FootballFixture, League, Market
from django.utils import timezone
from datetime import timedelta

# Check if there are active leagues
active_leagues = League.objects.filter(active=True)
print(f"Active leagues: {active_leagues.count()}")
for league in active_leagues[:5]:
    print(f"  - {league.name} (ID: {league.id})")

# Check recent fixtures
recent_fixtures = FootballFixture.objects.filter(
    match_date__gte=timezone.now() - timedelta(days=7)
).order_by('-match_date')[:10]
print(f"\nRecent fixtures: {recent_fixtures.count()}")
for fixture in recent_fixtures:
    print(f"  - {fixture}")
    print(f"    last_odds_update: {fixture.last_odds_update}")
    print(f"    last_score_update: {fixture.last_score_update}")
    print(f"    match_updated: {fixture.match_updated}")
    print(f"    Markets: {fixture.markets.count()}")

# Check if markets have recent odds
recent_markets = Market.objects.filter(
    last_updated_odds_api__gte=timezone.now() - timedelta(hours=24)
).count()
print(f"\nMarkets updated in last 24h: {recent_markets}")
```

### Step 2: Manually Trigger Update Tasks
```python
from football_data_app.tasks_apifootball import (
    run_apifootball_full_update_task,
    run_score_and_settlement_task
)

# Trigger full update (leagues, fixtures, odds)
result = run_apifootball_full_update_task.delay()
print(f"Full update task ID: {result.id}")

# Trigger scores update
result = run_score_and_settlement_task.delay()
print(f"Scores update task ID: {result.id}")
```

### Step 3: Check Task Execution
```bash
# Watch celery logs for task execution
docker-compose logs -f celery_cpu_worker

# Look for:
# - "TASK START: fetch_odds_for_single_event_task"
# - "Successfully processed and saved odds"
# - "TASK START: fetch_scores_for_league_task"
# - "Fixture X marked FINISHED. Score: X-X"
```

### Step 4: Verify API Responses
Check the logs for API responses:
```bash
docker-compose logs backend | grep "APIFootball"
```

Look for:
- "APIFootball Response: Status=200"
- "No odds data returned from API"
- "APIFootball HTTPError" or "APIFootballException"

## Recommended Actions

### For the Repository Maintainer

1. **Add logging to track update frequency:**
   - Already implemented ✓ (see `last_odds_update`, `last_score_update`)
   
2. **Add monitoring for stale data:**
   - Create a management command to report fixtures with stale odds/scores
   - Alert when data hasn't updated in X hours

3. **Improve error visibility:**
   - Already has comprehensive logging ✓
   - Consider adding a dashboard to show task health

4. **Document the update schedule:**
   - Document how often tasks run
   - Document what triggers each type of update

### For Users Experiencing the Issue

1. **Verify tasks are scheduled:**
   ```bash
   docker-compose exec backend python manage.py shell
   ```
   ```python
   from django_celery_beat.models import PeriodicTask
   tasks = PeriodicTask.objects.filter(enabled=True)
   for task in tasks:
       print(f"{task.name}: {task.crontab or task.interval}")
   ```

2. **Check recent task execution:**
   - Review Celery logs
   - Check database for recent `last_odds_update` and `last_score_update` timestamps

3. **Verify API connectivity:**
   - Test API key manually
   - Check API quota and rate limits

## Conclusion

**The implementation is CORRECT and complete.** 

Both odds and scores ARE being updated according to the APIFootball.com documentation:

- ✅ Odds: Fetched via `get_odds` endpoint, stored in Markets and MarketOutcomes
- ✅ Scores: Fetched via `get_events` endpoint (live and finished matches)
- ✅ Timestamps: `last_odds_update`, `last_score_update`, `match_updated` all tracked
- ✅ Update logic: Old data replaced with new data on each fetch

If odds/scores appear not to be updating, the issue is likely:
1. Tasks not running (Celery/scheduling issue)
2. API rate limits or authentication issues
3. No active leagues configured
4. Caching or display issue (data IS updated but not shown to users)

**Recommendation:** Follow the verification steps above to diagnose the specific issue in the deployment environment.
