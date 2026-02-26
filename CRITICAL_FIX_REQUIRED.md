# CRITICAL BUG: Odds Updates Deleting User Bets

## Severity: CRITICAL 🔴

## Issue

The current odds update mechanism has a **critical flaw** that causes user bets to be deleted when odds are updated.

## Root Cause

**File:** `tasks_apifootball.py`, lines 152-157

```python
# Delete old market if exists
deleted_count, _ = Market.objects.filter(
    fixture=fixture,
    bookmaker=bookmaker,
    api_market_key='h2h'
).delete()
```

**Cascade Chain:**
1. Market is deleted
2. MarketOutcome records are CASCADE deleted (FK relationship in `Market.outcomes`)
3. **Bet records are CASCADE deleted** (FK relationship in `Bet.market_outcome` with `on_delete=models.CASCADE`)
4. **User bets are LOST!**

**From customer_data/models.py:**
```python
class Bet(models.Model):
    market_outcome = models.ForeignKey(
        'football_data_app.MarketOutcome', 
        on_delete=models.CASCADE,  # <-- This causes bets to be deleted!
        related_name='bets'
    )
```

## Impact

- **Data Loss:** User bets are permanently deleted when odds are refreshed
- **Financial Impact:** Lost bet records means lost tracking of user wagers
- **Settlement Failure:** Bets that should be settled will never be found
- **User Trust:** Users lose their placed bets without explanation

## Solution

### Option 1: Update Instead of Delete (RECOMMENDED)

Instead of deleting and recreating markets, update existing markets and their outcomes.

**Pros:**
- Preserves all related data (bets, historical records)
- More efficient (UPDATE instead of DELETE + INSERT)
- No data loss risk

**Cons:**
- Slightly more complex logic

### Option 2: Protect Delete with CHECK

Add a check before deleting to prevent deletion if bets exist.

**Pros:**
- Simple to implement
- Prevents data loss

**Cons:**
- Odds won't update if bets exist
- Could lead to stale odds for popular matches

### Option 3: Change CASCADE to PROTECT

Change `Bet.market_outcome` foreign key to `on_delete=models.PROTECT`.

**Pros:**
- Prevents accidental deletion
- Database integrity enforced

**Cons:**
- Updates will fail if bets exist
- Requires Option 1 to be implemented first

## Recommended Implementation

**Implement Option 1 + Option 3 together:**

1. **Change odds update logic to UPDATE instead of DELETE** (Option 1)
2. **Change Bet model to use PROTECT** (Option 3)  
3. **Add migration** to update the foreign key constraint

This gives us:
- ✅ No data loss
- ✅ Odds can always be updated
- ✅ Database integrity protection
- ✅ Historical bet data preserved

## Implementation Plan

### Step 1: Update Odds Processing Logic

**File:** `tasks_apifootball.py`

Replace the delete-and-create pattern with an update-or-create pattern:

```python
def _process_apifootball_odds_data(fixture: FootballFixture, odds_data: dict):
    """
    Processes and saves odds/market data from APIFootball for a fixture.
    
    UPDATED: Now updates existing markets instead of deleting them.
    This prevents CASCADE deletion of user bets.
    """
    for bookmaker_data in odds_data.get('odd_bookmakers', []):
        bookmaker_name = bookmaker_data.get('bookmaker_name', 'Unknown')
        
        bookmaker, _ = Bookmaker.objects.get_or_create(
            api_bookmaker_key=bookmaker_name.lower().replace(' ', '_'),
            defaults={'name': bookmaker_name}
        )
        
        for odds_entry in bookmaker_data.get('bookmaker_odds', []):
            odd_1 = odds_entry.get('odd_1')
            odd_x = odds_entry.get('odd_x')
            odd_2 = odds_entry.get('odd_2')
            
            if odd_1 or odd_x or odd_2:
                category, _ = MarketCategory.objects.get_or_create(name='Match Winner')
                
                # UPDATE OR CREATE market instead of delete + create
                market, market_created = Market.objects.update_or_create(
                    fixture=fixture,
                    bookmaker=bookmaker,
                    api_market_key='h2h',
                    category=category,
                    defaults={
                        'last_updated_odds_api': timezone.now(),
                        'is_active': True
                    }
                )
                
                # UPDATE OR CREATE outcomes instead of recreating them
                if odd_1:
                    MarketOutcome.objects.update_or_create(
                        market=market,
                        outcome_name=fixture.home_team.name,
                        defaults={
                            'odds': Decimal(str(odd_1)),
                            'is_active': True
                        }
                    )
                
                if odd_x:
                    MarketOutcome.objects.update_or_create(
                        market=market,
                        outcome_name='Draw',
                        defaults={
                            'odds': Decimal(str(odd_x)),
                            'is_active': True
                        }
                    )
                
                if odd_2:
                    MarketOutcome.objects.update_or_create(
                        market=market,
                        outcome_name=fixture.away_team.name,
                        defaults={
                            'odds': Decimal(str(odd_2)),
                            'is_active': True
                        }
                    )
                
                # Mark outcomes as inactive if they no longer exist in the API response
                # This preserves historical bet references while indicating odds are no longer available
                market.outcomes.exclude(
                    outcome_name__in=[
                        name for name, odd in [
                            (fixture.home_team.name, odd_1),
                            ('Draw', odd_x),
                            (fixture.away_team.name, odd_2)
                        ] if odd
                    ]
                ).update(is_active=False)
```

### Step 2: Update Bet Model (Optional but Recommended)

**File:** `customer_data/models.py`

```python
class Bet(models.Model):
    market_outcome = models.ForeignKey(
        'football_data_app.MarketOutcome', 
        on_delete=models.PROTECT,  # Changed from CASCADE to PROTECT
        related_name='bets'
    )
```

**Migration:**
```bash
python manage.py makemigrations
python manage.py migrate
```

### Step 3: Add Tests

Create tests to verify:
1. Odds update preserves existing bets
2. Odds values are actually updated
3. Historical data is maintained

## Testing the Fix

### Before Fix (Current Behavior - BAD)
```python
# Create a bet
fixture = FootballFixture.objects.first()
market = fixture.markets.first()
outcome = market.outcomes.first()
bet = Bet.objects.create(market_outcome=outcome, amount=10)

# Update odds (triggers market delete)
_process_apifootball_odds_data(fixture, new_odds_data)

# Bet is GONE! ❌
assert not Bet.objects.filter(id=bet.id).exists()  # This passes (BAD!)
```

### After Fix (Expected Behavior - GOOD)
```python
# Create a bet
fixture = FootballFixture.objects.first()
market = fixture.markets.first()
outcome = market.outcomes.first()
bet = Bet.objects.create(market_outcome=outcome, amount=10)

# Update odds (now updates instead of deletes)
_process_apifootball_odds_data(fixture, new_odds_data)

# Bet still EXISTS! ✅
assert Bet.objects.filter(id=bet.id).exists()  # This should pass
# Odds are UPDATED! ✅
updated_outcome = MarketOutcome.objects.get(id=outcome.id)
assert updated_outcome.odds != outcome.odds  # Odds changed
```

## Priority

**CRITICAL - Implement IMMEDIATELY**

This bug causes data loss and affects the core betting functionality. It should be fixed before any new features are added.

## Related to Original Issue?

The original issue states "odds and scores are not being updated". This delete-and-recreate pattern could be causing issues if:
1. The deletion fails due to database constraints (in production)
2. The creation fails after deletion (data loss)
3. The transaction rolls back (odds appear not to update)

**Fixing this bug will likely resolve the "odds not updating" issue as well.**
