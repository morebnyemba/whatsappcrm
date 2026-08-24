# football_data_app/models.py
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings

# A reference to the User model, robust to custom user model swapping
USER_MODEL = settings.AUTH_USER_MODEL

class League(models.Model):
    """Stores information about a single sports league, e.g., English Premier League."""
    name = models.CharField(max_length=100)
    api_id = models.CharField(max_length=100, unique=True, help_text="The unique key for the league from the API (e.g., 'soccer_epl' or league_id from APIFootball).")
    sport_key = models.CharField(max_length=50, help_text="The general sport key, e.g., 'soccer'.")
    sport_group_name = models.CharField(max_length=100, null=True, blank=True, help_text="The general sport group name from the API, e.g., 'Soccer'.")
    short_name = models.CharField(max_length=200, null=True, blank=True, help_text="Short name or title for the league from API (e.g., EPL).")
    api_description = models.TextField(null=True, blank=True, help_text="Full description of the league from the API, if different from name.")
    active = models.BooleanField(default=True, help_text="Whether this league is currently tracked for updates.")
    logo_url = models.URLField(max_length=512, null=True, blank=True, help_text="URL for the league's logo.")
    country_id = models.CharField(max_length=50, null=True, blank=True, help_text="Country ID from APIFootball.")
    country_name = models.CharField(max_length=100, null=True, blank=True, help_text="Country name from APIFootball.")
    league_season = models.CharField(max_length=50, null=True, blank=True, help_text="Current season (e.g., '2023/2024').")
    last_fetched_events = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful event fetch for this league.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("League")
        verbose_name_plural = _("Leagues")
        ordering = ['name']

class Team(models.Model):
    """Stores information about a single sports team."""
    name = models.CharField(max_length=100, unique=True)
    api_team_id = models.CharField(max_length=100, null=True, blank=True, help_text="Unique team ID from the API, if available. May not always be provided.")
    logo_url = models.URLField(max_length=512, null=True, blank=True, help_text="URL for the team's logo.")
    badge_url = models.URLField(max_length=512, null=True, blank=True, help_text="Alternative badge/logo URL from APIFootball.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Team")
        verbose_name_plural = _("Teams")
        ordering = ['name']

class FootballFixture(models.Model):
    """Stores information about a single football match (an event)."""
    class FixtureStatus(models.TextChoices):
        SCHEDULED = 'SCHEDULED', _('Scheduled')
        LIVE = 'LIVE', _('Live')
        FINISHED = 'FINISHED', _('Finished')
        POSTPONED = 'POSTPONED', _('Postponed')
        CANCELLED = 'CANCELLED', _('Cancelled')

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name='fixtures')
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_fixtures')
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_fixtures')
    api_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="The unique event ID from The Odds API.")
    match_date = models.DateTimeField(null=True, blank=True, help_text="The scheduled start time of the fixture.")
    match_updated = models.DateTimeField(null=True, blank=True, help_text="Timestamp when the match was last updated by the API (from match_updated field). Per APIFootball.com documentation.")
    status = models.CharField(max_length=20, choices=FixtureStatus.choices, default=FixtureStatus.SCHEDULED)
    home_team_score = models.IntegerField(null=True, blank=True)
    away_team_score = models.IntegerField(null=True, blank=True)
    elapsed_minutes = models.IntegerField(null=True, blank=True, help_text="Minutes elapsed in a LIVE match (e.g. 62), from the provider's fixture status. Meaningless once the match isn't LIVE.")
    last_odds_update = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful odds fetch.")
    last_score_update = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful score fetch.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        date_str = self.match_date.strftime('%Y-%m-%d') if self.match_date else 'TBD'
        return f"{self.home_team.name} vs {self.away_team.name} on {date_str}"

    class Meta:
        verbose_name = _("Football Fixture")
        verbose_name_plural = _("Football Fixtures")
        ordering = ['-match_date']
        indexes = [
            # Every hot path filters on status and/or match_date, and this
            # table only ever grows (FINISHED fixtures accumulate for the
            # life of the deployment), so without these the per-minute
            # live-odds task, every browse tap and the odds-dispatch sweep
            # all sequential-scan the entire fixture history. Measured on a
            # 200k-row table with a production-like status mix: the
            # every-60s live-odds query goes 21.1ms -> 1.6ms, and (more
            # importantly) stops growing linearly with accumulated history.
            models.Index(fields=['status', 'match_date'], name='fixture_status_date_idx'),
            # dispatch_odds_fetching_after_events_v3's staleness sweep.
            models.Index(fields=['last_odds_update'], name='fixture_last_odds_idx'),
        ]

class Bookmaker(models.Model):
    """Stores information about a betting company."""
    name = models.CharField(max_length=100)
    api_bookmaker_key = models.CharField(max_length=50, unique=True, help_text="The unique key for the bookmaker from the API.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Bookmaker")
        verbose_name_plural = _("Bookmakers")
        ordering = ['name']

class MarketCategory(models.Model):
    """Categorizes different types of betting markets (e.g., 'Match Winner', 'Totals')."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Market Category")
        verbose_name_plural = _("Market Categories")
        ordering = ['name']

class Market(models.Model):
    """A specific betting market available for a fixture from a bookmaker."""
    fixture = models.ForeignKey(FootballFixture, on_delete=models.CASCADE, related_name='markets')
    bookmaker = models.ForeignKey(Bookmaker, on_delete=models.CASCADE, related_name='bookmaker_markets')
    category = models.ForeignKey(MarketCategory, on_delete=models.CASCADE, related_name='category_markets')
    api_market_key = models.CharField(max_length=50, help_text="The market key from the API, e.g., 'h2h', 'totals'.")
    last_updated_odds_api = models.DateTimeField(help_text="Timestamp of the market update from the API.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fixture} - {self.category.name} ({self.bookmaker.name})"

    class Meta:
        verbose_name = _("Market")
        verbose_name_plural = _("Markets")
        ordering = ['fixture', 'category']
        unique_together = ('fixture', 'bookmaker', 'api_market_key')
        indexes = [
            # Browse joins fixtures to their *active* markets on every tap
            # (betting_ux._bettable_fixtures_qs). unique_together already
            # indexes fixture as a leading column, but not alongside
            # is_active, which is the discriminating filter here.
            models.Index(fields=['fixture', 'is_active'], name='market_fixture_active_idx'),
        ]

class MarketOutcome(models.Model):
    """A possible outcome for a market with its associated odds."""
    class ResultStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        WON = 'WON', _('Won')
        LOST = 'LOST', _('Lost')
        PUSH = 'PUSH', _('Push / Void')

    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='outcomes')
    outcome_name = models.CharField(max_length=100, help_text="The name of the outcome (e.g., 'Manchester United', 'Over').")
    odds = models.DecimalField(max_digits=10, decimal_places=3)
    point_value = models.FloatField(null=True, blank=True, help_text="The point value for spread or totals markets (e.g., 2.5 for Over/Under).")
    result_status = models.CharField(max_length=10, choices=ResultStatus.choices, default=ResultStatus.PENDING)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        point_str = f" ({self.point_value})" if self.point_value is not None else ""
        return f"{self.outcome_name}{point_str} @ {self.odds}"

    class Meta:
        verbose_name = _("Market Outcome")
        verbose_name_plural = _("Market Outcomes")
        ordering = ['market', 'outcome_name']
        indexes = [
            # Outcomes are read filtered to is_active on every market/odds
            # render and on every bet placement validation.
            models.Index(fields=['market', 'is_active'], name='outcome_market_active_idx'),
        ]
        
class FixturePrediction(models.Model):
    """
    Model-generated win/draw/loss probabilities for a fixture.

    Produced by a statistical model (see predictions.py) from historical results
    already ingested via the football data API. Surfaced as plain-language copy
    in the WhatsApp fixture detail card. This is advisory only and never feeds
    bet placement or overrides real odds.
    """
    fixture = models.OneToOneField(FootballFixture, on_delete=models.CASCADE, related_name='prediction')
    prob_home = models.FloatField(help_text="Probability the home team wins (0-1).")
    prob_draw = models.FloatField(help_text="Probability of a draw (0-1).")
    prob_away = models.FloatField(help_text="Probability the away team wins (0-1).")
    expected_home_goals = models.FloatField(null=True, blank=True)
    expected_away_goals = models.FloatField(null=True, blank=True)
    method = models.CharField(max_length=30, default='poisson', help_text="Model used, e.g. 'poisson'.")
    data_points = models.IntegerField(default=0, help_text="Number of historical matches the estimate is based on (confidence).")
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Prediction for {self.fixture}: {self.prob_home:.0%}/{self.prob_draw:.0%}/{self.prob_away:.0%}"

    @property
    def favored_side(self) -> str:
        """'home', 'draw' or 'away' — whichever the model rates most likely."""
        return max((('home', self.prob_home), ('draw', self.prob_draw), ('away', self.prob_away)),
                   key=lambda x: x[1])[0]

    class Meta:
        verbose_name = _("Fixture Prediction")
        verbose_name_plural = _("Fixture Predictions")


class Configuration(models.Model):
    """Configuration for football data API providers."""
    
    PROVIDER_CHOICES = [
        ('API-Football', 'API-Football (api-football.com) - Recommended'),
        ('APIFootball', 'APIFootball (apifootball.com)'),
        ('The Odds API', 'The Odds API'),
    ]
    
    provider_name = models.CharField(
        max_length=50,
        choices=PROVIDER_CHOICES,
        default="APIFootball",
        help_text="Football data API provider. API-Football (api-football.com) is recommended for new installations."
    )
    email = models.EmailField(help_text="Contact email for this API configuration")
    api_key = models.CharField(max_length=100, help_text="API key for authentication")
    current_season = models.IntegerField(
        default=2024,
        help_text="Current season year for API-Football v3 (e.g., 2024). Used when fetching fixtures and standings."
    )
    is_active = models.BooleanField(default=True, help_text="Whether this configuration is currently active")
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    
    class Meta:
        verbose_name = _("Configuration")
        verbose_name_plural = _("Configurations")
        ordering = ['-is_active', '-created_at']

    def __str__(self):
        return f"{self.provider_name} ({self.email})"
    
