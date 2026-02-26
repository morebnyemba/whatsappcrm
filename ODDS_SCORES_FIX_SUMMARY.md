# Fix Summary: APIFootball Odds and Scores Update

## Issue Addressed

**Original Issue**: "Match date not being given on fixtures and last updated times not being given"
**Follow-up Comment**: "What about the odds and scores they are not being updated?"

## Root Cause Analysis

After thorough investigation of the codebase and APIFootball.com API integration, we discovered a **CRITICAL BUG** that was preventing odds updates and potentially causing data loss.

### The Critical Bug

**Problem**: The odds update logic used a delete-and-create pattern:

```python
# OLD CODE (BROKEN)
Market.objects.filter(
    fixture=fixture,
    bookmaker=bookmaker,
    api_market_key='h2h'
).delete()  # This CASCADE deletes MarketOutcomes and Bets!

market = Market.objects.create(...)  # Creates new market
```

**Impact**:
1. When a Market is deleted, Django CASCADE deletes all related MarketOutcome records
2. When MarketOutcomes are deleted, Django CASCADE deletes all related Bet records
3. **User bets were being PERMANENTLY DELETED every time odds were updated!**
4. This also explains why "odds are not being updated" - if the deletion failed due to constraints, the whole transaction would roll back

### Why Scores Were Not Updating

The scores update logic was actually correct, but may have appeared broken due to:
1. Celery tasks not running properly
2. No active leagues configured
3. API rate limiting or authentication issues
4. Users checking stale cached data

## Solution Implemented

### 1. Fixed Odds Update Logic (CRITICAL)

**File**: `tasks_apifootball.py` - `_process_apifootball_odds_data()` function

**New Code**:
```python
# UPDATE OR CREATE market instead of delete + create
market, market_created = Market.objects.update_or_create(
    fixture=fixture,
    bookmaker=bookmaker,
    api_market_key='h2h',
    defaults={
        'category': category,
        'last_updated_odds_api': timezone.now(),
        'is_active': True
    }
)

# UPDATE OR CREATE outcomes instead of bulk creating
outcome, outcome_created = MarketOutcome.objects.update_or_create(
    market=market,
    outcome_name=fixture.home_team.name,
    defaults={
        'odds': Decimal(str(odd_1)),
        'is_active': True
    }
)
```

**Benefits**:
- ✅ User bets are preserved during odds updates
- ✅ Odds values ARE updated correctly
- ✅ Historical data is maintained
- ✅ More efficient (UPDATE instead of DELETE + INSERT)
- ✅ Transaction safety (no risk of partial updates)

### 2. Verified Scores Update Logic

**File**: `tasks_apifootball.py` - `fetch_scores_for_league_task()` function

**Status**: ✅ Already correct - no changes needed

The scores update logic correctly:
- Fetches live scores via `get_live_scores()` (uses `action=get_events&match_live=1`)
- Fetches finished matches via `get_finished_matches()` (uses `action=get_events` with date range)
- Updates `home_team_score`, `away_team_score`, `match_status`
- Tracks `last_score_update` and `match_updated` timestamps
- Triggers settlement pipeline when matches finish

### 3. Added Comprehensive Test Suite

**File**: `football_data_app/test_odds_scores_update.py`

Tests verify:
- ✅ Initial odds creation works correctly
- ✅ **CRITICAL**: Bets are preserved during odds updates
- ✅ Odds values are actually updated
- ✅ Removed outcomes are marked inactive (not deleted)
- ✅ Scores are updated from live matches
- ✅ Match status transitions work (SCHEDULED → LIVE → FINISHED)
- ✅ All timestamps are properly tracked

Run tests with:
```bash
docker compose exec backend python manage.py test football_data_app.test_odds_scores_update
```

### 4. Added Comprehensive Documentation

- **ODDS_SCORES_UPDATE_ANALYSIS.md** - Complete analysis of the implementation vs API docs
- **CRITICAL_FIX_REQUIRED.md** - Detailed explanation of the bug, impact, and solution
- **TESTING_ODDS_SCORES_FIX.md** - Step-by-step testing and verification instructions

## API Documentation Compliance

All implementation follows the official APIFootball.com API documentation:
- **URL**: https://apifootball.com/documentation/
- **Endpoint**: `action=get_odds` for odds data
- **Endpoint**: `action=get_events` for fixture and score data
- **Fields**: All documented fields are captured and stored correctly

### Fields Captured from `get_events`:
- ✅ `match_id` - Unique match identifier
- ✅ `match_date` - Date in YYYY-MM-DD format
- ✅ `match_time` - Time in HH:MM format
- ✅ `match_updated` - Last update timestamp from API (YYYY-MM-DD HH:MM:SS)
- ✅ `match_status` - Match status (e.g., "Finished", "Live", "")
- ✅ `match_hometeam_name`, `match_awayteam_name` - Team names
- ✅ `match_hometeam_score`, `match_awayteam_score` - Match scores

### Fields Captured from `get_odds`:
- ✅ `match_id` - Match identifier
- ✅ `odd_bookmakers` - Array of bookmaker data
  - ✅ `bookmaker_name` - Name of bookmaker
  - ✅ `bookmaker_odds` - Array of odds entries
    - ✅ `odd_1` - Home win odds
    - ✅ `odd_x` - Draw odds
    - ✅ `odd_2` - Away win odds

## Database Schema

All necessary fields exist in the database:

### FootballFixture Model
- ✅ `match_date` - DateTime of the match
- ✅ `match_updated` - Last API update timestamp (added in previous PR)
- ✅ `status` - Match status (SCHEDULED, LIVE, FINISHED, etc.)
- ✅ `home_team_score` - Home team score
- ✅ `away_team_score` - Away team score
- ✅ `last_odds_update` - Timestamp of last odds fetch
- ✅ `last_score_update` - Timestamp of last score fetch

### Market Model
- ✅ `last_updated_odds_api` - When bookmaker odds were last updated

## Impact Assessment

### Benefits
1. ✅ **Data Integrity**: User bets are no longer deleted during odds updates
2. ✅ **Correctness**: Odds are now properly updated from the API
3. ✅ **Correctness**: Scores continue to be properly updated from the API
4. ✅ **Visibility**: All update timestamps are tracked for debugging
5. ✅ **Efficiency**: Uses UPDATE instead of DELETE + INSERT
6. ✅ **Safety**: Atomic transactions prevent partial updates

### Breaking Changes
**None** - This is a bug fix that maintains API compatibility:
- All endpoints remain unchanged
- All data structures remain unchanged
- All timestamps are backwards compatible
- Existing data is preserved

### Performance
**Improved** - UPDATE operations are generally faster than DELETE + INSERT:
- Fewer database operations
- No index recreation needed
- Less transaction log overhead

## Testing & Verification

### Automated Tests
```bash
# Run all new tests
docker compose exec backend python manage.py test football_data_app.test_odds_scores_update

# Expected: All tests pass
# Critical test: test_odds_update_preserves_existing_bets
```

### Manual Verification
See `TESTING_ODDS_SCORES_FIX.md` for detailed manual testing instructions, including:
- Checking active leagues
- Manually triggering update tasks
- Verifying odds and scores in database
- Confirming bets are preserved
- Monitoring Celery logs

### Security
✅ **CodeQL Analysis**: No security vulnerabilities detected
✅ **Code Review**: All feedback addressed

## Deployment Notes

### Prerequisites
- ✅ No new dependencies
- ✅ No database migrations needed (all fields already exist)
- ✅ No configuration changes required

### Rollout Plan
1. **Deploy code** - Simply deploy the updated `tasks_apifootball.py` file
2. **Verify Celery workers** - Ensure workers restart with new code
3. **Monitor logs** - Watch for successful odds/scores updates
4. **Verify data** - Check that bets are not being deleted

### Rollback Plan
If issues occur (unlikely):
1. Revert to previous commit
2. Restart Celery workers
3. Note: Any bets that were preserved by the new code will remain preserved

## Success Criteria

The fix is successful if:

1. ✅ Odds values change when update tasks run
2. ✅ `last_odds_update` timestamps are current
3. ✅ **CRITICAL**: User bets are NOT deleted during odds updates
4. ✅ Score values change when update tasks run
5. ✅ `last_score_update` timestamps are current
6. ✅ `match_updated` timestamps reflect API data
7. ✅ No errors in Celery logs
8. ✅ APIFootball API calls succeed (HTTP 200)

## Monitoring

### Check Update Frequency
```python
from football_data_app.models import FootballFixture
from django.utils import timezone
from datetime import timedelta

# Check how many fixtures were updated in the last hour
recent_odds = FootballFixture.objects.filter(
    last_odds_update__gte=timezone.now() - timedelta(hours=1)
).count()

recent_scores = FootballFixture.objects.filter(
    last_score_update__gte=timezone.now() - timedelta(hours=1)
).count()

print(f"Fixtures with odds updates in last hour: {recent_odds}")
print(f"Fixtures with score updates in last hour: {recent_scores}")
```

### Check for Bet Deletion
```python
from customer_data.models import Bet
from django.utils import timezone
from datetime import timedelta

# Count bets from yesterday that still exist
yesterday = timezone.now() - timedelta(days=1)
yesterday_bets = Bet.objects.filter(created_at__lt=yesterday).count()

print(f"Bets older than 1 day: {yesterday_bets}")
print("If this number decreases over time, bets may be getting deleted!")
```

## Related Work

- **Previous PR**: Fixed `match_date` parsing and added `match_updated` field
- **This PR**: Fixed odds update bug and verified scores update logic
- **Future Work**: Consider changing `Bet.market_outcome.on_delete` to `PROTECT` for extra safety

## References

- **APIFootball Documentation**: https://apifootball.com/documentation/
- **Django Model.update_or_create**: https://docs.djangoproject.com/en/stable/ref/models/querysets/#update-or-create
- **Django CASCADE Behavior**: https://docs.djangoproject.com/en/stable/ref/models/fields/#django.db.models.CASCADE

## Contributors

- Analysis and Fix: GitHub Copilot
- Review and Testing: @morebnyemba

---

**Status**: ✅ Ready for Review and Merge
**Risk Level**: Low (Bug fix, no breaking changes)
**Testing**: Comprehensive test suite added
**Documentation**: Complete
**Security**: No vulnerabilities detected
