# APIFootball Data Structure Fixes

## Issue
The issue reported that:
1. Match date not being given on fixtures
2. Last updated times not being given

## Root Causes

### 1. Match Date Not Being Captured Properly
**Per APIFootball.com Documentation:** https://apifootball.com/documentation/

The API returns:
- `match_date`: Date in YYYY-MM-DD format
- `match_time`: Time in **HH:MM** format (not HH:MM:SS)

**Problem:** The code was parsing with `%H:%M:%S` format, which would fail for the standard `HH:MM` format returned by the API.

**Fix:** Updated the date/time parsing in `tasks_apifootball.py` to:
1. Try `HH:MM` format first (per API documentation)
2. Fall back to `HH:MM:SS` format for backward compatibility
3. Better error handling and logging

### 2. Last Updated Times Not Being Captured
**Per APIFootball.com Documentation:** https://apifootball.com/documentation/

The API returns a `match_updated` field in the get_events endpoint that contains the timestamp when the match was last updated by the API.

**Problem:** This field was not being captured or stored in the database.

**Fix:** 
1. Added new `match_updated` field to the `FootballFixture` model
2. Updated `tasks_apifootball.py` to capture this field from both:
   - `fetch_events_for_league_task()` - when fetching fixtures
   - `fetch_scores_for_league_task()` - when updating scores
3. Added database migration to add the field
4. Updated admin interface to display the field

## Changes Made

### 1. Models (`models.py`)
```python
# Added new field
match_updated = models.DateTimeField(
    null=True, 
    blank=True, 
    help_text="Timestamp when the match was last updated by the API (from match_updated field). Per APIFootball.com documentation."
)
```

### 2. Tasks (`tasks_apifootball.py`)

**Date Parsing Fix:**
```python
# Per APIFootball.com documentation: https://apifootball.com/documentation/
# match_date is in YYYY-MM-DD format, match_time is in HH:MM format
match_datetime = None
if match_date and match_time:
    try:
        datetime_str = f"{match_date} {match_time}"
        # Try HH:MM format first (per APIFootball docs)
        try:
            match_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        except ValueError:
            # Fallback to HH:MM:SS format for backward compatibility
            match_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
        # Make timezone aware
        match_datetime = timezone.make_aware(match_datetime)
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse match datetime: {datetime_str}, error: {e}")
```

**Capturing match_updated:**
```python
# Per APIFootball.com documentation: https://apifootball.com/documentation/
# match_updated contains the last update timestamp from the API
match_updated_str = fixture_item.get('match_updated')

# Parse match_updated timestamp
match_updated = None
if match_updated_str:
    try:
        match_updated = datetime.strptime(match_updated_str, '%Y-%m-%d %H:%M:%S')
        match_updated = timezone.make_aware(match_updated)
    except (ValueError, TypeError) as e:
        logger.debug(f"Could not parse match_updated: {match_updated_str}, error: {e}")

# Store in fixture
fixture, fixture_created = FootballFixture.objects.update_or_create(
    api_id=match_id,
    defaults={
        # ... other fields ...
        'match_date': match_datetime,
        'match_updated': match_updated,  # NEW FIELD
    }
)
```

### 3. Admin Interface (`admin.py`)
Added `match_updated` to the list display for better visibility:
```python
list_display = ('id', 'fixture_display', 'league', 'status', 'match_date', 'match_updated', 'last_odds_update', 'last_score_update')
```

### 4. Serializers (`serializers.py`)
Fixed field names and added match_updated:
```python
class FootballFixtureSerializer(serializers.ModelSerializer):
    class Meta:
        model = FootballFixture
        fields = ['id', 'home_team', 'away_team', 'match_date', 'match_updated', 'status', 'markets']
```

### 5. Database Migration
Created migration `0004_add_match_updated_field.py` to add the new field.

**Note:** Migration files are excluded from git per `.gitignore` (line 40). Users should run:
```bash
python manage.py makemigrations
python manage.py migrate
```

## API Documentation References

All changes are based on the official APIFootball.com documentation:
https://apifootball.com/documentation/

### get_events Endpoint
Returns fixture data with:
- `match_id`: Match identifier
- `match_date`: Date in YYYY-MM-DD format
- `match_time`: Time in HH:MM format
- `match_updated`: Last update timestamp (YYYY-MM-DD HH:MM:SS)
- `match_status`: Status (e.g., "Finished", "", "Live")
- `match_hometeam_name`, `match_awayteam_name`: Team names
- `match_hometeam_score`, `match_awayteam_score`: Scores

### get_odds Endpoint
Returns odds data with:
- `match_id`: Match identifier
- `odd_bookmakers`: Array of bookmaker data
  - `bookmaker_name`: Name of bookmaker
  - `bookmaker_odds`: Array of odds entries
    - `odd_1`: Home win odds
    - `odd_x`: Draw odds
    - `odd_2`: Away win odds

## Testing

To test these changes:

1. **Run migrations:**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

2. **Fetch fresh data:**
   ```bash
   python manage.py shell
   >>> from football_data_app.tasks_apifootball import run_apifootball_full_update_task
   >>> run_apifootball_full_update_task.delay()
   ```

3. **Verify in admin:**
   - Navigate to Football Data App > Football Fixtures
   - Check that `match_date` is populated correctly
   - Check that `match_updated` shows the API's last update timestamp

4. **Check logs:**
   - Look for successful date parsing messages
   - Verify no "Could not parse match datetime" warnings for valid data

## Impact

### Benefits
1. ✅ Match dates are now correctly parsed from the APIFootball format
2. ✅ Last update timestamps from the API are captured and stored
3. ✅ Better visibility into when match data was last updated by the provider
4. ✅ Improved debugging capabilities with timestamp information
5. ✅ More robust date parsing with fallback support

### Breaking Changes

**API Serializer Field Name Change:**
- `FootballFixtureSerializer` field name changed from `commence_time` (incorrect) to `match_date` (correct)
- This affects API consumers that were using the `commence_time` field
- **Action Required:** Update any API clients to use `match_date` instead of `commence_time`
- **Rationale:** The old field name was incorrect and did not match the actual model field name. This is a bug fix that brings the API in line with the data model.

**Database Schema:**
- New `match_updated` field added to FootballFixture model
- No impact on existing data or queries
- New field is nullable and backward compatible
- Date parsing tries multiple formats for compatibility
- Existing data remains unchanged

## Future Improvements

Potential enhancements for future iterations:
1. Add `match_updated` to the filtering options in admin
2. Create alerts when matches haven't been updated in X hours
3. Display match_updated in the WhatsApp bot responses
4. Add analytics on API update frequency
