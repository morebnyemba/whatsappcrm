# Testing Instructions for Odds and Scores Update Fix

## Overview

This document provides instructions for testing the fixes made to the odds and scores update functionality, specifically addressing:

1. **CRITICAL FIX**: Preventing bet deletion during odds updates
2. Verifying odds are correctly updated from APIFootball.com
3. Verifying scores are correctly updated from APIFootball.com

## Prerequisites

- Docker and Docker Compose installed
- `.env` file configured with valid `API_FOOTBALL_KEY`
- Database migrations applied

## Running the Tests

### Option 1: Automated Tests

Run the test suite to verify the implementation:

```bash
# Start the Docker environment
docker compose up -d db redis backend

# Wait for services to be healthy
docker compose ps

# Run the odds/scores update tests
docker compose exec backend python manage.py test football_data_app.test_odds_scores_update --verbosity=2

# Expected output:
# - test_odds_update_creates_initial_market ... ok
# - test_odds_update_preserves_existing_bets ... ok (CRITICAL TEST)
# - test_odds_update_changes_values ... ok
# - test_odds_update_marks_removed_outcomes_inactive ... ok
# - test_score_update_from_live_match ... ok
# - test_match_status_update_to_finished ... ok
# - test_match_updated_timestamp ... ok
# - test_last_odds_update_timestamp ... ok
# - test_last_score_update_timestamp ... ok
```

### Option 2: Manual Verification

#### Step 1: Check Active Leagues

```bash
docker compose exec backend python manage.py shell
```

```python
from football_data_app.models import League
leagues = League.objects.filter(active=True)
print(f"Active leagues: {leagues.count()}")
for league in leagues[:5]:
    print(f"  - {league.name} (API ID: {league.api_id})")
```

Expected: At least one active league should exist.

#### Step 2: Manually Trigger Odds Update

```python
from football_data_app.tasks_apifootball import run_apifootball_full_update_task

# Trigger full update (leagues, fixtures, odds)
result = run_apifootball_full_update_task.delay()
print(f"Task ID: {result.id}")
print("Check Celery logs for task execution:")
print("  docker compose logs -f celery_cpu_worker")
```

#### Step 3: Verify Odds Were Updated

Wait a few minutes for the task to complete, then:

```python
from football_data_app.models import FootballFixture, Market
from django.utils import timezone
from datetime import timedelta

# Check recent fixtures with odds
fixtures_with_odds = FootballFixture.objects.filter(
    markets__isnull=False,
    match_date__gte=timezone.now(),
    match_date__lte=timezone.now() + timedelta(days=7)
).distinct()

print(f"\nFixtures with odds: {fixtures_with_odds.count()}")

for fixture in fixtures_with_odds[:5]:
    print(f"\n{fixture.home_team.name} vs {fixture.away_team.name}")
    print(f"  Match date: {fixture.match_date}")
    print(f"  Last odds update: {fixture.last_odds_update}")
    print(f"  Markets: {fixture.markets.count()}")
    
    for market in fixture.markets.all()[:2]:
        print(f"    {market.bookmaker.name}:")
        for outcome in market.outcomes.all():
            active = "✓" if outcome.is_active else "✗"
            print(f"      {active} {outcome.outcome_name}: {outcome.odds}")
```

Expected output:
- Fixtures should have markets
- Markets should have outcomes with odds
- `last_odds_update` should be recent (within last hour if task ran)

#### Step 4: Verify Bets Are Preserved During Updates

**CRITICAL TEST**: This verifies the fix for the bet deletion bug.

```python
from football_data_app.models import FootballFixture, Market, MarketOutcome
from customer_data.models import Bet, BetTicket, User, Wallet
from decimal import Decimal
from django.db import transaction

# Find a fixture with odds
fixture = FootballFixture.objects.filter(
    markets__isnull=False,
    status='SCHEDULED'
).first()

if not fixture:
    print("ERROR: No fixtures with odds found")
else:
    print(f"Testing with fixture: {fixture}")
    
    # Get a market outcome
    outcome = fixture.markets.first().outcomes.first()
    print(f"Outcome: {outcome.outcome_name} @ {outcome.odds}")
    
    # Create a test bet
    user = User.objects.first()
    if not user:
        print("ERROR: No users found. Create a user first.")
    else:
        # Get or create wallet
        wallet, _ = Wallet.objects.get_or_create(user=user, defaults={'balance': Decimal('1000')})
        
        # Create bet ticket
        ticket = BetTicket.objects.create(
            user=user,
            total_stake=Decimal('10.00'),
            potential_winnings=Decimal('25.00'),
            status='PENDING'
        )
        
        # Create bet
        bet = Bet.objects.create(
            ticket=ticket,
            market_outcome=outcome,
            amount=Decimal('10.00'),
            potential_winnings=Decimal('25.00'),
            status='PENDING'
        )
        
        bet_id = bet.id
        print(f"Created test bet ID: {bet_id}")
        
        # Now trigger odds update
        from football_data_app.tasks_apifootball import fetch_odds_for_single_event_task
        result = fetch_odds_for_single_event_task.delay(fixture.id)
        print(f"Triggered odds update task: {result.id}")
        print("Wait 30 seconds for task to complete...")
        
        import time
        time.sleep(30)
        
        # Check if bet still exists
        if Bet.objects.filter(id=bet_id).exists():
            print("✓ SUCCESS: Bet was preserved during odds update!")
            bet = Bet.objects.get(id=bet_id)
            print(f"  Bet still references outcome: {bet.market_outcome}")
            
            # Check if odds were updated
            outcome.refresh_from_db()
            print(f"  Current odds: {outcome.odds}")
        else:
            print("✗ FAILURE: Bet was deleted during odds update!")
            print("  This indicates the fix did not work correctly.")
```

Expected result: "✓ SUCCESS: Bet was preserved during odds update!"

#### Step 5: Manually Trigger Score Update

```python
from football_data_app.tasks_apifootball import run_score_and_settlement_task

# Trigger score update
result = run_score_and_settlement_task.delay()
print(f"Task ID: {result.id}")
print("Check Celery logs for task execution:")
print("  docker compose logs -f celery_cpu_worker")
```

#### Step 6: Verify Scores Were Updated

Wait a few minutes, then:

```python
from football_data_app.models import FootballFixture
from django.utils import timezone
from datetime import timedelta

# Check recent matches with scores
matches_with_scores = FootballFixture.objects.filter(
    home_team_score__isnull=False,
    away_team_score__isnull=False
).order_by('-last_score_update')[:10]

print(f"\nRecent matches with scores: {matches_with_scores.count()}")

for match in matches_with_scores:
    print(f"\n{match.home_team.name} vs {match.away_team.name}")
    print(f"  Score: {match.home_team_score} - {match.away_team_score}")
    print(f"  Status: {match.status}")
    print(f"  Match date: {match.match_date}")
    print(f"  Last score update: {match.last_score_update}")
    print(f"  Match updated (API): {match.match_updated}")
```

Expected output:
- Matches should have scores
- `last_score_update` should be recent
- `match_updated` should show when API last updated the match data

## Continuous Verification

### Check Task Schedule

Verify that periodic tasks are configured:

```bash
docker compose exec backend python manage.py shell
```

```python
from django_celery_beat.models import PeriodicTask

tasks = PeriodicTask.objects.filter(enabled=True)
print(f"Enabled periodic tasks: {tasks.count()}\n")

for task in tasks:
    schedule = task.crontab or task.interval
    print(f"Task: {task.name}")
    print(f"  Enabled: {task.enabled}")
    print(f"  Schedule: {schedule}")
    print(f"  Task: {task.task}")
    print()
```

Expected tasks:
- `football_data_app.run_apifootball_full_update` (runs every few hours)
- `football_data_app.run_score_and_settlement_task` (runs frequently during match days)

### Monitor Celery Logs

Watch the logs to see tasks executing:

```bash
# Watch odds update tasks
docker compose logs -f celery_cpu_worker | grep -i "odds"

# Watch score update tasks
docker compose logs -f celery_cpu_worker | grep -i "score"

# Watch for errors
docker compose logs -f celery_cpu_worker | grep -i "error"
```

### Check Database Directly

Connect to the database and check timestamps:

```bash
docker compose exec db psql -U whatsappcrm_user -d whatsappcrm_db
```

```sql
-- Check recent odds updates
SELECT 
    id, 
    home_team_id, 
    away_team_id, 
    last_odds_update,
    last_score_update,
    match_updated
FROM football_data_app_footballfixture
WHERE last_odds_update IS NOT NULL
ORDER BY last_odds_update DESC
LIMIT 10;

-- Check recent score updates
SELECT 
    id, 
    home_team_id, 
    away_team_id, 
    home_team_score,
    away_team_score,
    status,
    last_score_update
FROM football_data_app_footballfixture
WHERE last_score_update IS NOT NULL
ORDER BY last_score_update DESC
LIMIT 10;

-- Check if any bets exist (to verify they're not being deleted)
SELECT COUNT(*) as total_bets FROM customer_data_bet;
```

## Troubleshooting

### Issue: No Odds Being Fetched

**Possible causes:**
1. No active leagues configured
2. API key invalid or rate limited
3. Celery workers not running
4. No upcoming fixtures in the date range

**Solutions:**
```bash
# Check active leagues
docker compose exec backend python manage.py shell -c "from football_data_app.models import League; print(League.objects.filter(active=True).count())"

# Check API key
docker compose exec backend python manage.py shell -c "import os; print('API Key:', os.getenv('API_FOOTBALL_KEY', 'NOT SET'))"

# Check Celery workers
docker compose ps | grep celery

# Manually fetch fixtures
docker compose exec backend python manage.py shell -c "from football_data_app.tasks_apifootball import run_apifootball_full_update_task; run_apifootball_full_update_task.delay()"
```

### Issue: No Scores Being Updated

**Possible causes:**
1. No live or recently finished matches
2. API not returning score data
3. Fixtures not in database

**Solutions:**
```bash
# Check if there are fixtures to update
docker compose exec backend python manage.py shell -c "from football_data_app.models import FootballFixture; from django.utils import timezone; print('LIVE:', FootballFixture.objects.filter(status='LIVE').count()); print('Recent:', FootballFixture.objects.filter(match_date__lt=timezone.now(), status='SCHEDULED').count())"

# Manually trigger score update
docker compose exec backend python manage.py shell -c "from football_data_app.tasks_apifootball import run_score_and_settlement_task; run_score_and_settlement_task.delay()"
```

### Issue: Bets Being Deleted

If you find bets are still being deleted after the fix:

1. **Verify the fix was applied:**
   ```bash
   docker compose exec backend grep -A 20 "UPDATE OR CREATE market" football_data_app/tasks_apifootball.py
   ```
   Should show `update_or_create` instead of `delete()` + `create()`

2. **Check for other code paths:**
   ```bash
   docker compose exec backend grep -r "Market.objects.*delete()" football_data_app/
   ```
   Should not find any other places deleting markets

3. **Check database constraints:**
   ```bash
   docker compose exec backend python manage.py shell -c "from customer_data.models import Bet; print(Bet._meta.get_field('market_outcome').remote_field.on_delete)"
   ```
   Current: `CASCADE` (bets deleted with outcomes)
   Recommended change: `PROTECT` (prevent deletion if bets exist)

## Success Criteria

The fixes are working correctly if:

1. ✅ Odds values change when `fetch_odds_for_single_event_task` runs
2. ✅ `last_odds_update` timestamp is updated for fixtures
3. ✅ `last_updated_odds_api` timestamp is updated for markets
4. ✅ **CRITICAL**: Bets are NOT deleted when odds are updated
5. ✅ Score values change when `fetch_scores_for_league_task` runs
6. ✅ `last_score_update` timestamp is updated when scores change
7. ✅ `match_updated` timestamp is captured from the API
8. ✅ Match status changes to LIVE and then FINISHED appropriately
9. ✅ No errors in Celery logs related to odds/scores updates
10. ✅ APIFootball API calls are successful (HTTP 200 responses)

## Documentation References

All implementation is based on:
- **APIFootball.com API Documentation**: https://apifootball.com/documentation/
- Specifically: `get_events` and `get_odds` endpoints
- Field mappings documented in code comments
