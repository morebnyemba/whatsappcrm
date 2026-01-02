# Odds Display Fix - All 8 Betting Market Types

## Problem Statement

After PR #72, the system was only displaying 2 out of 8 betting market types:
- ✓ Match Winner (1X2) - bet_id: 1
- ✓ Both Teams To Score (BTTS) - bet_id: 8

The following 6 betting markets were NOT being displayed:
- ✗ Double Chance - bet_id: 2
- ✗ Asian Handicap - bet_id: 3
- ✗ Draw No Bet - bet_id: 4
- ✗ Total Goals (Over/Under) - bet_id: 5
- ✗ Odd/Even Goals - bet_id: 7
- ✗ Correct Score - bet_id: 9

## Root Cause Analysis

### Issue Location
**File**: `whatsappcrm_backend/football_data_app/tasks_api_football_v3.py`
**Function**: `fetch_odds_for_single_event_v3_task` (line 694)

### Original Code
```python
logger.debug(f"Calling APIFootballV3Client.get_odds(fixture_id={api_fixture_id})...")
odds_data = client.get_odds(fixture_id=api_fixture_id)
logger.info(f"API returned {len(odds_data) if odds_data else 0} odds items for fixture {fixture.id}")
```

### Why This Was Wrong
The API-Football v3 API supports a `bet_id` parameter to filter which betting markets to return. When **NOT** specified, the API only returns a default subset of betting markets (typically bet_ids 1 and 8).

From the API-Football v3 client (`api_football_v3_client.py`, line 317):
```python
def get_odds(
    self,
    fixture_id: Optional[int] = None,
    league_id: Optional[int] = None,
    season: Optional[int] = None,
    date: Optional[str] = None,
    bookmaker_id: Optional[int] = None,
    bet_id: Optional[int] = None  # ← This parameter was not being used!
) -> List[dict]:
```

## Solution Implemented

### New Code
Modified `fetch_odds_for_single_event_v3_task` to explicitly request all 8 betting market types:

```python
# Fetch odds for all 8 betting market types
# Bet IDs per API-Football v3 documentation:
# 1: Match Winner, 2: Double Chance, 3: Asian Handicap, 4: Draw No Bet,
# 5: Goals Over/Under, 7: Odd/Even, 8: Both Teams To Score, 9: Correct Score
bet_ids = [1, 2, 3, 4, 5, 7, 8, 9]
all_odds_data = []

logger.debug(f"Fetching odds for fixture {api_fixture_id} across {len(bet_ids)} bet types...")
for bet_id in bet_ids:
    try:
        logger.debug(f"Calling APIFootballV3Client.get_odds(fixture_id={api_fixture_id}, bet_id={bet_id})...")
        bet_odds = client.get_odds(fixture_id=api_fixture_id, bet_id=bet_id)
        if bet_odds:
            all_odds_data.extend(bet_odds)
            logger.debug(f"  ✓ Bet type {bet_id}: {len(bet_odds)} odds items returned")
        else:
            logger.debug(f"  - Bet type {bet_id}: No odds available")
    except APIFootballV3Exception as e:
        # Log but don't fail the entire task if one bet type fails
        logger.warning(f"  ✗ Bet type {bet_id} failed: {e}")
        continue

odds_data = all_odds_data
logger.info(f"API returned {len(odds_data)} total odds items for fixture {fixture.id} across {len(bet_ids)} bet types")
```

### Key Improvements
1. **Explicit bet_id requests**: Calls the API once for each of the 8 bet types
2. **Aggregation**: Collects all odds data into a single list for processing
3. **Error handling**: Individual bet type failures won't crash the entire task
4. **Enhanced logging**: Shows which bet types succeeded/failed and how many odds returned

## Verification

### 1. Check Logs After Running Tasks
After running `run_api_football_v3_full_update_task`, you should see logs like:
```
Fetching odds for fixture 123456 across 8 bet types...
  ✓ Bet type 1: 3 odds items returned
  ✓ Bet type 2: 3 odds items returned
  ✓ Bet type 3: 6 odds items returned
  ✓ Bet type 4: 2 odds items returned
  ✓ Bet type 5: 8 odds items returned
  - Bet type 7: No odds available
  ✓ Bet type 8: 2 odds items returned
  ✓ Bet type 9: 15 odds items returned
API returned 39 total odds items for fixture 12345 across 8 bet types
```

### 2. Verify Display in WhatsApp Messages
When users request fixtures, they should now see all available betting markets:

```
⚽ *Upcoming Matches*

🏆 *Premier League* (ID: 4550)
🗓️ Fri, Jan 02 - 08:45 PM
Manchester United vs Liverpool

*Match Winner (1X2):*
  - Manchester United: *2.10* (ID: 183798)
  - Draw: *3.40* (ID: 184112)
  - Liverpool: *2.90* (ID: 184974)

*Double Chance:*
  - Home/Draw (1X): *1.30* (ID: 185001)
  - Home/Away (12): *1.52* (ID: 185002)
  - Draw/Away (X2): *1.65* (ID: 185003)

*Total Goals (Over/Under):*
  - Over 2.5: *1.85* (ID: 185010)
  - Under 2.5: *1.95* (ID: 185011)

*Both Teams To Score:*
  - Yes: *1.70* (ID: 185446)
  - No: *2.05* (ID: 184018)

*Draw No Bet:*
  - Manchester United: *1.60* (ID: 185020)
  - Liverpool: *2.20* (ID: 185021)

*Asian Handicap:*
  - Manchester United (-0.5): *1.90* (ID: 185030)
  - Liverpool (+0.5): *1.95* (ID: 185031)

*Correct Score (Top Picks):*
  - 1-1: *6.50* (ID: 185040)
  - 2-1: *8.00* (ID: 185041)
  - 1-0: *9.00* (ID: 185042)
  - 2-0: *10.00* (ID: 185043)

*Odd/Even Goals:*
  - Odd: *1.90* (ID: 185050)
  - Even: *1.95* (ID: 185051)
```

### 3. Database Verification
Check that all bet types are being stored:

```sql
-- Count markets by category
SELECT c.name, COUNT(*) as count
FROM football_data_app_marketcategory c
JOIN football_data_app_market m ON m.category_id = c.id
GROUP BY c.name
ORDER BY count DESC;
```

Expected output:
```
name                      | count
--------------------------+-------
Match Winner              | 150
Both Teams To Score       | 150
Totals                    | 450  (multiple Over/Under lines)
Correct Score             | 750  (many score combinations)
Asian Handicap            | 300  (multiple handicap lines)
Double Chance             | 150
Draw No Bet               | 150
Odd/Even Goals            | 150
```

## Testing the Fix

### Method 1: Run Full Update Task
```bash
docker-compose exec backend python manage.py shell
```
```python
from football_data_app.tasks_api_football_v3 import run_api_football_v3_full_update_task
run_api_football_v3_full_update_task.delay()
```

### Method 2: Test Single Fixture
```python
from football_data_app.tasks_api_football_v3 import fetch_odds_for_single_event_v3_task
from football_data_app.models import FootballFixture

# Get a scheduled fixture
fixture = FootballFixture.objects.filter(status='SCHEDULED').first()
if fixture:
    fetch_odds_for_single_event_v3_task.delay(fixture.id)
```

### Method 3: Test Display
Send a WhatsApp message to the bot:
```
fixtures
```

Check that all 8 betting market types are displayed (when available for that match).

## API Considerations

### Rate Limiting
Each fixture now makes **8 API calls** (one per bet type) instead of 1. This increases API usage by 8x.

**Mitigation**:
1. Rate limiter is already in place (see `rate_limiter.py`)
2. Jitter delay (0.5-3.0s) spreads out requests
3. Error handling prevents cascading failures

**Monitor**:
- API quota usage via API-Football dashboard
- Check logs for "Rate limit reached (429)" warnings
- Adjust `API_FOOTBALL_MAX_REQUESTS_PER_MINUTE` if needed

### Subscription Tiers
Some API-Football subscription tiers may:
- Not include all bet types
- Have different bet_id values
- Return empty data for certain markets

**Check if certain bet types consistently return no data** - this may indicate subscription limitations.

## Bet Type Mapping Reference

**Note**: Bet type IDs follow API-Football v3 convention. bet_id 6 is reserved in the API but not commonly documented or used, which is why we fetch bet_ids [1, 2, 3, 4, 5, 7, 8, 9].

| bet_id | Market Name | api_market_key | Category Name |
|--------|-------------|----------------|---------------|
| 1 | Match Winner | h2h | Match Winner |
| 2 | Double Chance | double_chance | Double Chance |
| 3 | Asian Handicap | handicap | Asian Handicap |
| 4 | Draw No Bet | draw_no_bet | Draw No Bet |
| 5 | Goals Over/Under | totals | Totals |
| 6 | *Reserved/Unused* | - | - |
| 7 | Odd/Even | odd_even | Odd/Even Goals |
| 8 | Both Teams Score | btts | Both Teams To Score |
| 9 | Exact/Correct Score | correct_score | Correct Score |

## Related Files

### Modified Files
- `whatsappcrm_backend/football_data_app/tasks_api_football_v3.py` (line 694-740)

### Related Files (No Changes Required)
- `whatsappcrm_backend/football_data_app/utils.py` - Display formatting (already supports all 8 types)
- `whatsappcrm_backend/football_data_app/api_football_v3_client.py` - API client (already supports bet_id parameter)

## Rollback Plan

If this change causes issues (e.g., excessive API usage), revert to single call:

```python
# Original code (fetches default bet types only)
odds_data = client.get_odds(fixture_id=api_fixture_id)
```

Or fetch only specific bet types:
```python
# Fetch only essential bet types to reduce API calls
bet_ids = [1, 5, 8]  # Match Winner, Totals, BTTS
```

## Future Enhancements

1. **Configurable Bet Types**: Allow admin to select which bet types to fetch
2. **Caching**: Cache odds data to reduce API calls
3. **Batch Requests**: Investigate if API supports fetching multiple bet types in one call
4. **Smart Fetching**: Only fetch bet types that are commonly available for the league/fixture

## Success Criteria

✅ All 8 betting market types are fetched from API
✅ All available bet types are displayed in WhatsApp messages  
✅ No increase in task failure rates
✅ API rate limits are respected
✅ Enhanced logging shows which bet types are available/unavailable

## References

- API-Football v3 Documentation: https://www.api-football.com/documentation-v3
- Odds endpoint: https://www.api-football.com/documentation-v3#tag/Odds
- SUPPORTED_BET_TYPES.md - Full list of betting markets and their display format
