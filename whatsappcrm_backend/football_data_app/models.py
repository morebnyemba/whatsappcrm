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
    api_id = models.CharField(max_length=100, unique=True, help_text="The unique key for the league from the API (e.g., 'soccer_epl').")
    sport_key = models.CharField(max_length=50, help_text="The general sport key, e.g., 'soccer'.")
    active = models.BooleanField(default=True, help_text="Whether this league is currently tracked for updates.")
    logo_url = models.URLField(max_length=512, null=True, blank=True, help_text="URL for the league's logo.")
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
    logo_url = models.URLField(max_length=512, null=True, blank=True, help_text="URL for the team's logo.")
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
    api_id = models.CharField(max_length=100, unique=True, help_text="The unique event ID from The Odds API.")
    match_date = models.DateTimeField(help_text="The scheduled start time of the fixture.")
    status = models.CharField(max_length=20, choices=FixtureStatus.choices, default=FixtureStatus.SCHEDULED)
    home_team_score = models.IntegerField(null=True, blank=True)
    away_team_score = models.IntegerField(null=True, blank=True)
    last_odds_update = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful odds fetch.")
    last_score_update = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful score fetch.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.home_team.name} vs {self.away_team.name} on {self.match_date.strftime('%Y-%m-%d')}"

    class Meta:
        verbose_name = _("Football Fixture")
        verbose_name_plural = _("Football Fixtures")
        ordering = ['-match_date']

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
    fixture_display = models.ForeignKey(FootballFixture, on_delete=models.CASCADE, related_name='markets')
    bookmaker = models.ForeignKey(Bookmaker, on_delete=models.CASCADE, related_name='markets')
    category = models.ForeignKey(MarketCategory, on_delete=models.CASCADE, related_name='markets')
    api_market_key = models.CharField(max_length=50, help_text="The market key from the API, e.g., 'h2h', 'totals'.")
    last_updated_odds_api = models.DateTimeField(help_text="Timestamp of the market update from the API.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fixture_display} - {self.category.name} ({self.bookmaker.name})"

    class Meta:
        verbose_name = _("Market")
        verbose_name_plural = _("Markets")
        ordering = ['fixture_display', 'category']
        unique_together = ('fixture_display', 'bookmaker', 'api_market_key')

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