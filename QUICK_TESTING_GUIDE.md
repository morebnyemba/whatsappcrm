# Quick Testing Guide - Odds Fetching Fix

## What Was Fixed
The system now fetches odds immediately when fixtures are created, instead of waiting for the entire pipeline to complete.

## How to Test

### 1. Run the Full Update Task
```bash
# From your host machine
docker-compose exec backend python manage.py shell

# In the Django shell
from football_data_app.tasks_api_football_v3 import run_api_football_v3_full_update_task
result = run_api_football_v3_full_update_task.delay()
print(f"Task ID: {result.id}")
```

### 2. Watch the Logs
```bash
# In another terminal, watch the worker logs
docker-compose logs -f backend

# Or if you have separate worker containers
docker-compose logs -f celery_worker
```

### 3. Look for These Log Messages

#### Success Indicators:
✅ `"Dispatching odds fetching tasks for X scheduled fixtures..."`
- This means fixtures were created and odds tasks were dispatched

✅ `"API returned X odds items for fixture Y"`
- This means the API is returning odds data

✅ `"✓ Odds processing complete for fixture X: Y bookmakers (Z new), A markets, B outcomes"`
- This means odds were successfully processed and saved

#### Potential Issues:
⚠️ `"API returned 0 odds items for fixture X"`
- API has no odds for this fixture yet (common for future matches)
- Check if the match is too far in the future
- Verify your API subscription includes odds access

⚠️ `"No scheduled fixtures to fetch odds for"`
- No fixtures were created in this run
- Check if the date range has any matches
- Verify leagues are properly configured

⚠️ `"Failed to dispatch odds fetching tasks: ..."`
- Task dispatch error (rare)
- Check Celery worker status
- Check queue configuration

### 4. Verify in Database
```bash
# From your host machine
docker-compose exec backend python manage.py shell

# In the Django shell
from football_data_app.models import Bookmaker, Market, MarketOutcome, FootballFixture

# Check bookmakers
print(f"Bookmakers: {Bookmaker.objects.count()}")
for bm in Bookmaker.objects.all()[:5]:
    print(f"  - {bm.name}")

# Check markets
print(f"\nMarkets: {Market.objects.count()}")

# Check outcomes
print(f"\nOutcomes: {MarketOutcome.objects.count()}")

# Check fixtures with odds
fixtures_with_odds = FootballFixture.objects.filter(last_odds_update__isnull=False)
print(f"\nFixtures with odds: {fixtures_with_odds.count()}")

# Show a sample fixture with odds
if fixtures_with_odds.exists():
    fixture = fixtures_with_odds.first()
    print(f"\nSample: {fixture.home_team.name} vs {fixture.away_team.name}")
    print(f"  Markets: {fixture.markets.count()}")
    for market in fixture.markets.all()[:3]:
        print(f"    - {market.category.name} ({market.bookmaker.name})")
        for outcome in market.outcomes.all()[:3]:
            print(f"      * {outcome.outcome_name}: {outcome.odds}")
```

### 5. Check Specific Fixture Odds
```bash
# In Django shell
from football_data_app.models import FootballFixture

# Find a specific fixture
fixtures = FootballFixture.objects.filter(
    status='SCHEDULED'
).order_by('match_date')[:5]

for fixture in fixtures:
    print(f"\n{fixture.home_team.name} vs {fixture.away_team.name}")
    print(f"  Match Date: {fixture.match_date}")
    print(f"  Last Odds Update: {fixture.last_odds_update}")
    print(f"  Markets: {fixture.markets.count()}")
```

## Expected Results

### For a Successful Run:
1. **Fixtures Created**: Should see fixtures being created in logs
2. **Odds Dispatched**: Should see "Dispatching odds fetching tasks..." message
3. **Odds Processed**: Should see "✓ Odds processing complete..." messages
4. **Database Populated**: 
   - Bookmakers table should have entries (e.g., bet365, Betway, etc.)
   - Markets table should have entries
   - MarketOutcome table should have odds values

### Timing:
- Fixtures should appear within 1-2 minutes
- Odds should start appearing within 5 minutes
- Full completion depends on number of leagues/fixtures

## Troubleshooting

### No Odds Appearing

1. **Check API Subscription**
   ```bash
   # Test API directly
   curl -X GET "https://v3.football.api-sports.io/odds?fixture=FIXTURE_ID" \
     -H "x-apisports-key: YOUR_API_KEY"
   ```
   
2. **Check Celery Workers**
   ```bash
   docker-compose ps
   # All workers should be "Up"
   
   docker-compose exec backend celery -A whatsappcrm_backend inspect active
   # Should show active tasks
   ```

3. **Check Queue Status**
   ```bash
   docker-compose exec backend celery -A whatsappcrm_backend inspect stats
   ```

### Odds Only for Some Fixtures
This is normal! Odds availability depends on:
- How far in the future the match is
- League popularity
- Bookmaker coverage
- API subscription level

Major leagues (Premier League, La Liga, etc.) typically have odds 1-2 weeks in advance.
Minor leagues may only have odds 1-2 days before the match.

## Monitoring in Production

### Key Metrics to Track:
1. **Odds Coverage Rate**: Percentage of scheduled fixtures with odds
   ```python
   from football_data_app.models import FootballFixture
   from django.utils import timezone
   from datetime import timedelta
   
   now = timezone.now()
   next_week = now + timedelta(days=7)
   
   total = FootballFixture.objects.filter(
       status='SCHEDULED',
       match_date__range=(now, next_week)
   ).count()
   
   with_odds = FootballFixture.objects.filter(
       status='SCHEDULED',
       match_date__range=(now, next_week),
       last_odds_update__isnull=False
   ).count()
   
   print(f"Coverage: {with_odds}/{total} ({with_odds/total*100:.1f}%)")
   ```

2. **Average Odds Update Latency**: Time from fixture creation to first odds update
3. **API Success Rate**: Track "API returned 0 odds" vs successful responses

## Next Steps

If everything is working:
1. ✅ Odds should now be fetched automatically
2. ✅ Monitor logs for the first few runs
3. ✅ Set up scheduled tasks if not already configured

If issues persist:
1. Check the detailed troubleshooting in `ODDS_FETCHING_FIX.md`
2. Verify API subscription includes odds endpoint
3. Check API quotas and rate limits
