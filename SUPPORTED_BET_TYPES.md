# Supported Betting Options - API-Football Integration

## Overview

This document lists all the betting markets supported by the WhatsApp CRM football betting system when displaying fixtures to users. The system fetches odds from API-Football v3 and displays them in a user-friendly format.

## Rate Limiting

**Important**: The system implements rate limiting to ensure compliance with API-Football's request limits:
- **Default**: Maximum 300 requests per minute
- **Configurable**: Set `API_FOOTBALL_MAX_REQUESTS_PER_MINUTE` in settings or environment variable
- **Automatic handling**: Requests are automatically throttled and queued when limit is approached
- **Graceful degradation**: System waits and retries when rate limit is exceeded

## Supported Betting Markets

### 1. Match Winner (1X2)
**Market Keys**: `h2h`, `1x2`, `match_winner`

The most basic bet - pick who will win the match or if it will be a draw.

**Options**:
- Home Win (1)
- Draw (X)
- Away Win (2)

**Example Display**:
```
*Match Winner (1X2):*
  - Manchester United: *2.10* (ID: 12345)
  - Draw: *3.40* (ID: 12346)
  - Liverpool: *2.90* (ID: 12347)
```

### 2. Double Chance
**Market Keys**: `double_chance`, `doublechance`

Combine two of the three possible outcomes, reducing risk but with lower odds.

**Options**:
- Home/Draw (1X) - Home team wins or draw
- Home/Away (12) - Either team wins (no draw)
- Draw/Away (X2) - Away team wins or draw

**Example Display**:
```
*Double Chance:*
  - Home/Draw (1X): *1.30* (ID: 12350)
  - Home/Away (12): *1.52* (ID: 12351)
  - Draw/Away (X2): *1.65* (ID: 12352)
```

### 3. Total Goals (Over/Under)
**Market Keys**: `totals`, `alternate_totals`, `goals_over_under`, `totals_1h`, `totals_2h`

Bet on whether the total goals scored will be over or under a specific number. Now supports full-time, 1st half, and 2nd half markets.

**Common Lines**:
- Over/Under 0.5
- Over/Under 1.5
- Over/Under 2.5 (most popular)
- Over/Under 3.5
- Over/Under 4.5

**Example Display**:
```
*Total Goals (Over/Under):*
  - Over 2.5: *1.85* (ID: 12360)
  - Under 2.5: *1.95* (ID: 12361)
  - Over 3.5: *2.70* (ID: 12362)
  - Under 3.5: *1.45* (ID: 12363)

*Total Goals (1st Half):*
  - Over 0.5: *1.45* (ID: 12364)
  - Under 0.5: *2.70* (ID: 12365)

*Total Goals (2nd Half):*
  - Over 1.5: *1.75* (ID: 12366)
  - Under 1.5: *2.05* (ID: 12367)
```

**Note**: Up to 3 most common lines are displayed per market type to avoid message overflow.

### 4. Both Teams To Score (BTTS)
**Market Keys**: `btts`, `both_teams_score`

Bet on whether both teams will score at least one goal each.

**Options**:
- Yes - Both teams score
- No - At least one team doesn't score

**Example Display**:
```
*Both Teams To Score:*
  - Yes: *1.70* (ID: 12370)
  - No: *2.05* (ID: 12371)
```

### 5. Draw No Bet
**Market Keys**: `draw_no_bet`, `drawnob`

If the match ends in a draw, your stake is refunded. You only win/lose if there's a winner.

**Options**:
- Home Win
- Away Win

**Example Display**:
```
*Draw No Bet:*
  - Manchester United: *1.60* (ID: 12380)
  - Liverpool: *2.20* (ID: 12381)
```

### 6. Asian Handicap
**Market Keys**: `handicap`, `asian_handicap`, `spreads`, `handicap_1h`, `handicap_2h`

One team gets a virtual head start (or deficit). **All available handicap lines are now displayed** (previously only the most balanced line was shown).

**Common Lines**:
- -0.5, 0.0, +0.5 (most common)
- -1.0, -1.5, +1.0, +1.5
- -2.0, -2.5, +2.0, +2.5

**Example Display**:
```
*Asian Handicap:*
  - Manchester United (+0.5): *1.30* (ID: 12387)
  - Liverpool (-0.5): *2.08* (ID: 12388)
  - Manchester United (-0.5): *1.90* (ID: 12390)
  - Liverpool (+0.5): *1.95* (ID: 12391)
  - Manchester United (-1.5): *4.15* (ID: 12392)
  - Liverpool (+1.5): *1.22* (ID: 12393)

*Asian Handicap (1st Half):*
  - Manchester United (+0.0): *1.51* (ID: 12394)
  - Liverpool (-0.0): *2.32* (ID: 12395)

*Asian Handicap (2nd Half):*
  - Manchester United (+0.0): *1.51* (ID: 12396)
  - Liverpool (-0.0): *2.32* (ID: 12397)
```

**How to Read**:
- Negative handicap (-0.5): Team must win by more than the handicap
- Positive handicap (+0.5): Team can lose by less than the handicap or draw/win

### 7. Correct Score
**Market Keys**: `correct_score`, `correctscore`

Predict the exact final score. Top 4 most likely scores are displayed.

**Example Display**:
```
*Correct Score (Top Picks):*
  - 1-1: *6.50* (ID: 12400)
  - 2-1: *8.00* (ID: 12401)
  - 1-0: *9.00* (ID: 12402)
  - 2-0: *10.00* (ID: 12403)
```

### 8. Odd/Even Goals
**Market Keys**: `odd_even`, `oddeven`, `goals_odd_even`

Bet on whether the total number of goals will be odd or even.

**Options**:
- Odd (1, 3, 5, 7, etc.)
- Even (0, 2, 4, 6, etc.)

**Example Display**:
```
*Odd/Even Goals:*
  - Odd: *1.90* (ID: 12410)
  - Even: *1.95* (ID: 12411)
```

## Additional Markets (Available but not displayed by default)

These markets are supported by API-Football and **will be displayed if available** (previously truncated):

### 9. Half Time / Full Time (HT/FT)
Predict the result at half-time and full-time. All available options displayed.

### 10. First/Last Team to Score
Bet on which team will score first or last. All available options displayed.

### 11. Clean Sheet
Bet on whether a team will keep a clean sheet (no goals conceded). All available options displayed.

### 12. Win to Nil
Bet on a team winning without conceding. All available options displayed.

### 13. Exact Number of Goals
Bet on the precise total number of goals (0, 1, 2, 3, 4+, etc.). All available options displayed.

**Note**: All unrecognized markets will now display **all available outcomes** instead of being truncated to 10 options.

## Bet Placement

To place a bet on any of the displayed options, users can:

1. **Note the Outcome ID** displayed next to each option (e.g., "ID: 12345")
2. **Send a bet message** with:
   ```
   [Fixture ID] [Outcome ID]
   Stake $[Amount]
   ```

**Example**:
```
123 12345
Stake $10
```

This would place a $10 bet on outcome ID 12345 from fixture 123.

## Message Format and Limits

- Maximum WhatsApp message size: 4096 characters
- Messages are automatically split when they exceed this limit
- Each fixture display is optimized to show the most relevant betting options
- Odds include the outcome ID for easy bet placement

## Rate Limit Management

The system automatically manages API rate limits:

1. **Request Tracking**: Every API call is tracked within a rolling 60-second window
2. **Automatic Throttling**: When approaching the limit, requests are queued
3. **Graceful Waiting**: If limit is reached, system waits for window reset
4. **Retry Logic**: Failed requests due to rate limiting are automatically retried
5. **Logging**: Rate limit usage is logged for monitoring

### Configuration

Set your rate limit based on your API-Football subscription plan:

**Environment Variable**:
```bash
API_FOOTBALL_MAX_REQUESTS_PER_MINUTE=300  # Adjust based on your plan
```

**Common Plan Limits**:
- Free: 10 requests/minute
- Basic: 30 requests/minute  
- Pro: 100 requests/minute
- Ultra: 300 requests/minute

## Market Key Mapping

The system recognizes multiple API market keys for flexibility across different data sources:

| Betting Market | Primary Key | Alternative Keys |
|---------------|-------------|------------------|
| Match Winner | `h2h` | `1x2`, `match_winner` |
| Double Chance | `double_chance` | `doublechance` |
| Total Goals | `totals` | `alternate_totals`, `goals_over_under` |
| Total Goals (1st Half) | `totals_1h` | - |
| Total Goals (2nd Half) | `totals_2h` | - |
| BTTS | `btts` | `both_teams_score` |
| Draw No Bet | `draw_no_bet` | `drawnob` |
| Asian Handicap | `handicap` | `asian_handicap`, `spreads` |
| Asian Handicap (1st Half) | `handicap_1h` | - |
| Asian Handicap (2nd Half) | `handicap_2h` | - |
| Correct Score | `correct_score` | `correctscore` |
| Odd/Even | `odd_even` | `oddeven`, `goals_odd_even` |

## Implementation Notes

- **Best Odds Selection**: When multiple bookmakers offer odds for the same outcome, the system displays the best (highest) odds available
- **Outcome IDs**: Each outcome has a unique database ID used for bet placement
- **Market Aggregation**: Markets from multiple bookmakers are aggregated to show the best available odds
- **Real-time Updates**: Odds are refreshed periodically based on configured staleness settings
- **Smart Formatting**: Display automatically adjusts based on available markets to avoid overwhelming users

## Future Enhancements

Potential additions in future updates:

1. User preferences for which markets to display
2. Customizable default markets per user
3. More advanced markets (Player props, Team props)
4. Live betting odds during matches
5. Odds movement indicators (↑↓)
6. Historical odds tracking
7. Multi-bet (accumulator) support with combined odds calculation

## API-Football Documentation

For more information about API-Football betting markets:
- Official Documentation: https://www.api-football.com/documentation-v3
- Bookmakers Endpoint: `/odds/bookmakers`
- Bet Types Endpoint: `/odds/bets`
- Odds Endpoint: `/odds`

## Support

For issues or questions:
1. Check logs for rate limiting warnings
2. Verify API-Football subscription plan limits
3. Review configuration settings
4. Contact support with error details
