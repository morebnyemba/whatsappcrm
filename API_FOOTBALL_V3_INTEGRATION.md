# API-Football v3 Integration Guide (api-football.com)

This document explains the integration with **API-Football v3** from **api-football.com** (with dash), which is now the **recommended primary provider** for all football and odds fetching tasks.

## 🔄 Important: API Provider Clarification

There are **TWO DIFFERENT APIs** with similar names:

### 1. **API-Football** (api-football.com) - ✅ RECOMMENDED PRIMARY
- **Website**: https://www.api-football.com/
- **Documentation**: https://www.api-football.com/documentation-v3  
- **Base URL**: `https://v3.football.api-sports.io/`
- **Authentication**: `x-apisports-key` header
- **Client File**: `api_football_v3_client.py`
- **Provider Name in DB**: `"API-Football"`
- **Env Variable**: `API_FOOTBALL_V3_KEY`
- **Features**: Comprehensive data, better odds coverage, more reliable

### 2. **APIFootball** (apifootball.com) - 🔄 LEGACY
- **Website**: https://apifootball.com/
- **Documentation**: https://apifootball.com/documentation/
- **Base URL**: `https://apiv3.apifootball.com/`
- **Authentication**: `APIkey` parameter
- **Client File**: `apifootball_client.py`
- **Provider Name in DB**: `"APIFootball"`
- **Env Variable**: `API_FOOTBALL_KEY`
- **Status**: Still supported for backward compatibility

## 🚀 Getting Started with API-Football v3

### Step 1: Obtain an API Key

1. Visit [api-football.com](https://www.api-football.com/)
2. Sign up for an account
3. Choose a plan (Free tier available for testing)
4. Copy your API key from the dashboard

### Step 2: Configure the API Key

You have two options for configuration:

#### Option A: Environment Variable (Recommended for Production)

Add to your `.env` file:

```env
API_FOOTBALL_V3_KEY=your_actual_api_key_here
API_FOOTBALL_V3_CURRENT_SEASON=2024
```

#### Option B: Database Configuration (Flexible, can be changed via Admin)

1. Log into the Django admin panel
2. Navigate to **Football Data App > Configurations**
3. Click "Add Configuration"
4. Fill in:
   - **Provider Name**: API-Football
   - **Email**: Your contact email
   - **API Key**: Your API-Football v3 API key
   - **Is Active**: ✓ (checked)
5. Save

### Step 3: Verify the Integration

Test the client directly:

```python
from football_data_app.api_football_v3_client import APIFootballV3Client

# Initialize client (will use env var or database config)
client = APIFootballV3Client()

# Test: Get available leagues
leagues = client.get_leagues(country="England", season=2024)
print(f"Found {len(leagues)} English leagues")

# Test: Get upcoming fixtures
fixtures = client.get_fixtures(league_id=39, season=2024, status='NS')
print(f"Found {len(fixtures)} upcoming fixtures")
```

## 📊 API Endpoints Comparison

| Data Type | API-Football v3 Endpoint | APIFootball (Legacy) Endpoint |
|-----------|-------------------------|-------------------------------|
| Leagues | `/leagues` | `?action=get_leagues` |
| Fixtures | `/fixtures` | `?action=get_events` |
| Live Scores | `/fixtures?live=all` | `?action=get_events&match_live=1` |
| Odds | `/odds` | `?action=get_odds` |
| Standings | `/standings` | `?action=get_standings` |
| Teams | `/teams` | `?action=get_teams` |
| Players | `/players` | N/A |
| H2H | `/fixtures/headtohead` | `?action=get_H2H` |

## 🏗️ Data Structure Differences

### Fixtures Response Structure

**API-Football v3:**
```json
{
  "response": [
    {
      "fixture": {
        "id": 123456,
        "date": "2024-08-13T18:00:00+00:00",
        "timestamp": 1660404000,
        "venue": {
          "id": 678,
          "name": "Old Trafford",
          "city": "Manchester"
        }
      },
      "league": {
        "id": 39,
        "name": "Premier League",
        "country": "England",
        "season": 2024
      },
      "teams": {
        "home": {
          "id": 33,
          "name": "Manchester United",
          "logo": "..."
        },
        "away": {
          "id": 34,
          "name": "Liverpool",
          "logo": "..."
        }
      },
      "goals": {
        "home": 2,
        "away": 1
      }
    }
  ]
}
```

**APIFootball (Legacy):**
```json
[
  {
    "match_id": "123456",
    "match_date": "2024-08-13",
    "match_time": "18:00",
    "match_hometeam_name": "Manchester United",
    "match_awayteam_name": "Liverpool",
    "match_hometeam_score": "2",
    "match_awayteam_score": "1",
    "league_id": "39"
  }
]
```

## 🔧 Using the API-Football v3 Client

### Basic Usage Examples

```python
from football_data_app.api_football_v3_client import APIFootballV3Client

client = APIFootballV3Client()

# Get English Premier League fixtures
fixtures = client.get_fixtures(
    league_id=39,  # Premier League
    season=2024,
    date_from='2024-01-01',
    date_to='2024-12-31'
)

# Get odds for a specific fixture
odds = client.get_fixture_odds(fixture_id=123456)

# Get league standings
standings = client.get_standings(
    league_id=39,
    season=2024
)

# Get live fixtures
live_fixtures = client.get_live_fixtures()

# Get team information
teams = client.get_teams(
    league_id=39,
    season=2024
)

# Get player statistics
players = client.get_players(
    team_id=33,
    season=2024
)

# Get head-to-head matches
h2h = client.get_head_to_head(
    team1_id=33,  # Man United
    team2_id=34,  # Liverpool
    last=10  # Last 10 matches
)
```

## 🎯 Migrating from Legacy APIFootball

If you're currently using the legacy APIFootball.com (without dash):

### 1. Code Changes

**Old (Legacy):**
```python
from football_data_app.apifootball_client import APIFootballClient

client = APIFootballClient()
fixtures = client.get_fixtures(league_id='39')  # league_id as string
```

**New (Recommended):**
```python
from football_data_app.api_football_v3_client import APIFootballV3Client

client = APIFootballV3Client()
fixtures = client.get_fixtures(league_id=39, season=2024)  # league_id as int, season required
```

### 2. Configuration Changes

**Old Environment Variable:**
```env
API_FOOTBALL_KEY=your_old_key
```

**New Environment Variable:**
```env
API_FOOTBALL_V3_KEY=your_new_key
API_FOOTBALL_V3_CURRENT_SEASON=2024
```

### 3. Database Configuration

Update or create a new Configuration entry in Django Admin:
- Change **Provider Name** from "APIFootball" to "API-Football"
- Update the **API Key** with your api-football.com v3 key

### 4. Key Differences to Handle

| Aspect | Legacy APIFootball | API-Football v3 |
|--------|-------------------|-----------------|
| League ID Type | String | Integer |
| Season Parameter | Optional | Required for most endpoints |
| Date Format | Date + Time separate | ISO 8601 timestamp |
| Response Format | Array of objects | `{"response": [...]}` wrapper |
| Team ID Field | `match_hometeam_id` | `teams.home.id` |
| Status Values | "Finished", "" | "FT", "NS", "LIVE", etc. |

## ⚙️ Configuration Parameters

Add these to your `settings.py` (already configured):

```python
# API-Football v3 Configuration
API_FOOTBALL_V3_KEY = os.environ.get('API_FOOTBALL_V3_KEY')
API_FOOTBALL_V3_CURRENT_SEASON = int(os.environ.get('API_FOOTBALL_V3_CURRENT_SEASON', '2024'))

# Operational Parameters
API_FOOTBALL_V3_LEAD_TIME_DAYS = 7
API_FOOTBALL_V3_EVENT_DISCOVERY_STALENESS_HOURS = 6
API_FOOTBALL_V3_UPCOMING_STALENESS_MINUTES = 60
API_FOOTBALL_V3_ASSUMED_COMPLETION_MINUTES = 120
API_FOOTBALL_V3_MAX_EVENT_RETRIES = 3
API_FOOTBALL_V3_EVENT_RETRY_DELAY = 300
```

## 📈 API Rate Limits

Be aware of your plan's rate limits:

| Plan | Requests/Day | Requests/Minute | Cost |
|------|--------------|-----------------|------|
| Free | 100 | 10 | $0 |
| Basic | 3,000 | 30 | ~$10/month |
| Pro | 30,000 | 100 | ~$30/month |
| Ultra | 300,000 | 300 | ~$100/month |

**Note**: Limits vary by plan and may change. Check [api-football.com pricing](https://www.api-football.com/pricing) for current information.

## 🧪 Testing the Integration

### Manual Test Script

Create a test script `test_api_football_v3.py`:

```python
from football_data_app.api_football_v3_client import APIFootballV3Client

def test_api_football_v3():
    client = APIFootballV3Client()
    
    print("✓ Client initialized")
    
    # Test 1: Get leagues
    print("\n1. Testing get_leagues...")
    leagues = client.get_leagues(country="England")
    print(f"   Found {len(leagues)} English leagues")
    
    # Test 2: Get fixtures
    print("\n2. Testing get_fixtures...")
    fixtures = client.get_fixtures(league_id=39, season=2024, status='NS')
    print(f"   Found {len(fixtures)} upcoming Premier League fixtures")
    
    # Test 3: Get live fixtures
    print("\n3. Testing get_live_fixtures...")
    live = client.get_live_fixtures()
    print(f"   Found {len(live)} live fixtures")
    
    # Test 4: Get standings
    print("\n4. Testing get_standings...")
    standings = client.get_standings(league_id=39, season=2024)
    print(f"   Retrieved standings: {len(standings)} entries")
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    test_api_football_v3()
```

Run it:
```bash
python manage.py shell < test_api_football_v3.py
```

## 🔍 Troubleshooting

### "API Key must be configured" Error

**Solution**: 
1. Check your `.env` file has `API_FOOTBALL_V3_KEY`
2. Or create a Configuration entry in Django Admin with provider "API-Football"

### "No response data" or Empty Results

**Possible causes**:
1. Invalid league ID (try 39 for Premier League)
2. Wrong season (use current or recent season like 2024)
3. No matches scheduled for the specified filters

**Solution**: Try with known working parameters:
```python
fixtures = client.get_fixtures(league_id=39, season=2024)  # Premier League
```

### Rate Limit Errors (429 Status)

**Solution**:
1. Check your API plan limits at api-football.com
2. Implement caching for frequently accessed data
3. Reduce polling frequency
4. Upgrade your plan if needed

### Authentication Errors (401, 403)

**Solution**:
1. Verify your API key is correct
2. Check your subscription is active
3. Ensure you're using `x-apisports-key` header (handled by client)

## 📚 Additional Resources

- **Official Documentation**: https://www.api-football.com/documentation-v3
- **API Dashboard**: https://www.api-football.com/account
- **Coverage Page**: https://www.api-football.com/coverage
- **Community Forum**: https://rapidapi.com/api-sports/api/api-football/discussions

## 🆘 Support

For issues with:
- **API-Football API**: Visit https://www.api-football.com/contact
- **Integration Code**: Check GitHub issues or logs
- **Django Models**: Review `football_data_app/models.py`
- **Client Implementation**: See `api_football_v3_client.py`

## ✅ Benefits of API-Football v3

1. **Better Coverage**: More leagues, competitions, and data points
2. **Enhanced Odds**: More bookmakers and bet types
3. **Player Statistics**: Detailed player data and statistics
4. **Head-to-Head**: Historical match data between teams
5. **Real-time Updates**: Better live score support
6. **Professional API**: More reliable, better documented
7. **Active Development**: Regular updates and new features

## 🔜 Next Steps

1. **Get your API key** from api-football.com
2. **Configure** the key in your `.env` file
3. **Test** the client with the examples above
4. **Update tasks** to use API-Football v3 client (if creating new tasks)
5. **Monitor** API usage on your dashboard
6. **Optimize** by caching and reducing unnecessary calls

---

**Note**: The legacy APIFootball.com (without dash) implementation remains available for backward compatibility but is not recommended for new development. All new features and improvements will focus on API-Football v3.
