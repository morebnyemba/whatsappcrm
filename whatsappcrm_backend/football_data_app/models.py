from django.db import models
from django.conf import settings # For ForeignKey to User model
from django.core.validators import MinValueValidator
import uuid # For unique identifiers like bet IDs

# --- Core Football Data Models (enhanced) ---

class League(models.Model):
    api_league_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=100, null=True, blank=True)
    logo_url = models.URLField(null=True, blank=True)
    # Add other league-specific details if needed (e.g., season, type like 'League' or 'Cup')

    def __str__(self):
        return self.name

class Team(models.Model):
    api_team_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=10, null=True, blank=True) # e.g., MUN, LIV
    logo_url = models.URLField(null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    # Add other team-specific details if needed

    def __str__(self):
        return self.name

class FootballFixture(models.Model):
    match_api_id = models.CharField(max_length=100, unique=True, db_index=True) # From api-football.com fixture.id
    league = models.ForeignKey(League, related_name='fixtures', on_delete=models.SET_NULL, null=True, blank=True)
    home_team = models.ForeignKey(Team, related_name='home_fixtures', on_delete=models.SET_NULL, null=True, blank=True)
    away_team = models.ForeignKey(Team, related_name='away_fixtures', on_delete=models.SET_NULL, null=True, blank=True)
    
    match_date = models.DateTimeField(db_index=True) # UTC
    status_short = models.CharField(max_length=10, db_index=True) # e.g., NS, FT, HT, PST (from api-football.com fixture.status.short)
    status_long = models.CharField(max_length=100, null=True) # e.g., "Not Started", "Match Finished" (from api-football.com fixture.status.long)
    
    venue_name = models.CharField(max_length=255, null=True, blank=True)
    referee = models.CharField(max_length=255, null=True, blank=True)
    round = models.CharField(max_length=100, null=True, blank=True)

    home_team_score = models.IntegerField(null=True, blank=True)
    away_team_score = models.IntegerField(null=True, blank=True)
    halftime_home_score = models.IntegerField(null=True, blank=True)
    halftime_away_score = models.IntegerField(null=True, blank=True)
    extratime_home_score = models.IntegerField(null=True, blank=True)
    extratime_away_score = models.IntegerField(null=True, blank=True)
    penalty_home_score = models.IntegerField(null=True, blank=True)
    penalty_away_score = models.IntegerField(null=True, blank=True)

    # Timestamp from the API for when the fixture data itself was last updated
    api_fixture_timestamp = models.DateTimeField(null=True, blank=True) # from fixture.timestamp
    
    # Indicates if the fixture results are confirmed and can be used for settlement
    is_result_confirmed = models.BooleanField(default=False, db_index=True)
    last_updated_from_api = models.DateTimeField(auto_now=True)

    def __str__(self):
        home_name = self.home_team.name if self.home_team else "N/A"
        away_name = self.away_team.name if self.away_team else "N/A"
        return f"{home_name} vs {away_name} on {self.match_date.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['match_date']

# --- Betting Related Models ---

class Bookmaker(models.Model):
    api_bookmaker_id = models.IntegerField(unique=True, db_index=True) # from api-football.com
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class MarketCategory(models.Model):
    """e.g., Full Time Result, Over/Under, Handicap, Correct Score, Player Props"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name

class Market(models.Model):
    """Represents a specific betting market for a fixture offered by a bookmaker.
       e.g., "Match Winner" for Fixture X by Bookmaker Y.
       This links a fixture, a bookmaker, and a market category to specific odds.
    """
    fixture = models.ForeignKey(FootballFixture, related_name='markets', on_delete=models.CASCADE)
    bookmaker = models.ForeignKey(Bookmaker, related_name='markets', on_delete=models.CASCADE)
    category = models.ForeignKey(MarketCategory, related_name='markets', on_delete=models.SET_NULL, null=True)
    
    # For markets like Over/Under X.5 goals, handicap values etc.
    # e.g. for Over/Under, market_parameter could be "2.5". For Asian Handicap, "-1.5".
    market_parameter = models.CharField(max_length=50, null=True, blank=True, help_text="e.g., 2.5 for Over/Under, -1.5 for Handicap")
    
    is_active = models.BooleanField(default=True, db_index=True) # Can be suspended by bookie
    last_updated_odds_api = models.DateTimeField(null=True, blank=True) # from odds.update field in api-football

    class Meta:
        unique_together = ('fixture', 'bookmaker', 'category', 'market_parameter') # Ensure uniqueness
        ordering = ['fixture', 'category', 'market_parameter']

    def __str__(self):
        param = f" ({self.market_parameter})" if self.market_parameter else ""
        return f"{self.category.name}{param} for {self.fixture} by {self.bookmaker.name}"

class MarketOutcome(models.Model):
    """Represents a specific outcome within a market and its odds.
       e.g., For "Match Winner" market: Home Win, Draw, Away Win.
       For "Over/Under 2.5": Over, Under.
    """
    market = models.ForeignKey(Market, related_name='outcomes', on_delete=models.CASCADE)
    # Name of the outcome, e.g., "Home", "Draw", "Away", "Over", "Under", "Player A to score"
    # This could be standardized or come from the API (api-football 'value' for bets)
    outcome_name = models.CharField(max_length=255)
    odds = models.DecimalField(max_digits=8, decimal_places=3)
    
    # For settlement purposes
    RESULTING_CHOICES = [
        ('PENDING', 'Pending'),
        ('WIN', 'Win'),
        ('LOSS', 'Loss'),
        ('VOID', 'Void/Push'), # For voided bets or pushed stakes
    ]
    result_status = models.CharField(max_length=10, choices=RESULTING_CHOICES, default='PENDING', db_index=True)
    
    is_suspended = models.BooleanField(default=False) # If this specific outcome is suspended

    class Meta:
        unique_together = ('market', 'outcome_name')
        ordering = ['market', 'outcome_name']

    def __str__(self):
        return f"{self.outcome_name} ({self.odds}) for Market ID {self.market.id}"

# --- User, Wallet, Bet Models ---

class UserWallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, validators=[MinValueValidator(0)])
    bonus_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, validators=[MinValueValidator(0)])
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Wallet - Balance: {self.balance}"

class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAWAL', 'Withdrawal'),
        ('BET_PLACEMENT', 'Bet Placement'),
        ('BET_WINNING', 'Bet Winning'),
        ('BET_REFUND', 'Bet Refund/Void'),
        ('BONUS_AWARD', 'Bonus Awarded'),
        # Add other types as needed
    ]
    wallet = models.ForeignKey(UserWallet, related_name='transactions', on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    description = models.TextField(null=True, blank=True)
    related_bet_id = models.CharField(max_length=36, null=True, blank=True, db_index=True) # Link to Bet.id if applicable
    
    # Before and after balances can be useful for auditing
    balance_before = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, null=True)

    def __str__(self):
        return f"{self.transaction_type} of {self.amount} for {self.wallet.user.username} at {self.timestamp}"


class Bet(models.Model):
    BET_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('WON', 'Won'),
        ('LOST', 'Lost'),
        ('VOIDED', 'Voided'),
        ('CASHED_OUT', 'Cashed Out'),
        # Potentially more statuses
    ]
    BET_TYPE_CHOICES = [
        ('SINGLE', 'Single'),
        ('ACCUMULATOR', 'Accumulator'), # aka Parlay or Multi
        # System bets (Yankee, Lucky 15 etc.) would require more complex logic
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False) # Public Bet ID
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='bets', on_delete=models.CASCADE)
    stake = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    potential_winnings = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_winnings = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_odds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True) # Combined odds for accumulators
    
    bet_type = models.CharField(max_length=20, choices=BET_TYPE_CHOICES, default='SINGLE')
    status = models.CharField(max_length=20, choices=BET_STATUS_CHOICES, default='PENDING', db_index=True)
    
    placed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    settled_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Denormalized for easier display, but primary truth is in BetSelection
    # number_of_selections = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"Bet {self.id} by {self.user.username} - Status: {self.status}"

    class Meta:
        ordering = ['-placed_at']


class BetSelection(models.Model):
    """A single selection within a Bet (especially useful for accumulators)."""
    bet = models.ForeignKey(Bet, related_name='selections', on_delete=models.CASCADE)
    # This links to the specific outcome the user bet on
    market_outcome = models.ForeignKey(MarketOutcome, on_delete=models.PROTECT) # Protect so it's not deleted if outcome is removed before settlement (handle this case)
    
    # Odds at the time of bet placement (Markets.odds can change)
    odds_at_placement = models.DecimalField(max_digits=8, decimal_places=3)
    
    # Result status for this specific leg of an accumulator
    result_status = models.CharField(max_length=10, choices=MarketOutcome.RESULTING_CHOICES, default='PENDING', db_index=True)

    # Denormalize fixture info for quick display in bet slip, but MarketOutcome -> Market -> Fixture is the source of truth
    fixture_description = models.CharField(max_length=255, null=True, blank=True, help_text="e.g., Man Utd vs Chelsea")
    market_description = models.CharField(max_length=255, null=True, blank=True, help_text="e.g., Match Winner")
    outcome_description = models.CharField(max_length=255, null=True, blank=True, help_text="e.g., Home")


    def __str__(self):
        return f"Selection for Bet {self.bet.id}: {self.market_outcome}"

    class Meta:
        unique_together = ('bet', 'market_outcome') # A user can't bet on the same outcome twice in the same bet slip

# --- (Optional) Event model for very detailed fixture events (goals, cards) ---
# This is similar to previous suggestions but can be linked for settlement if a market depends on it
# e.g. "Player X to score"
# class FixtureEvent(models.Model):
#     fixture = models.ForeignKey(FootballFixture, related_name='events', on_delete=models.CASCADE)
#     api_event_id = models.CharField(max_length=100, null=True, blank=True)
#     event_type = models.CharField(max_length=50) # 'Goal', 'Card', 'subst'
#     event_detail = models.CharField(max_length=100, null=True, blank=True) # 'Normal Goal', 'Penalty'
#     team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True)
#     # player = models.ForeignKey(Player, ...) # If you add a Player model
#     player_name = models.CharField(max_length=255, null=True, blank=True)
#     # assist_player_name = models.CharField(max_length=255, null=True, blank=True)
#     event_minute = models.IntegerField(null=True, blank=True)
#     # ... other fields ...