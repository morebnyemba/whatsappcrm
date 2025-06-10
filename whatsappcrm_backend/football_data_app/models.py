# football_data_app/models.py
from django.db import models
from django.utils.translation import gettext_lazy as _

class League(models.Model):
    """
    League model to store information about football leagues.
    """
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    season = models.CharField(max_length=20)
    api_id = models.CharField(max_length=50, unique=True)
    logo_url = models.URLField(null=True, blank=True)
    sport_key = models.CharField(max_length=50, null=True, blank=True)
    sport_title = models.CharField(max_length=100, null=True, blank=True)
    active = models.BooleanField(default=True)
    last_fetched_events = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.season})"

    class Meta:
        verbose_name = _("League")
        verbose_name_plural = _("Leagues")
        ordering = ['name', 'season']

class Team(models.Model):
    """
    Team model to store information about football teams.
    """
    name = models.CharField(max_length=100)
    api_id = models.CharField(max_length=50, unique=True)
    logo_url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Team")
        verbose_name_plural = _("Teams")
        ordering = ['name']

class FootballFixture(models.Model):
    """
    FootballFixture model to store information about football matches.
    """
    FIXTURE_STATUS = [
        ('SCHEDULED', 'Scheduled'),
        ('LIVE', 'Live'),
        ('FINISHED', 'Finished'),
        ('POSTPONED', 'Postponed'),
        ('CANCELLED', 'Cancelled'),
    ]

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name='fixtures')
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_fixtures')
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_fixtures')
    api_id = models.CharField(max_length=50, unique=True)
    match_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=FIXTURE_STATUS, default='SCHEDULED')
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} - {self.match_date}"

    class Meta:
        verbose_name = _("Football Fixture")
        verbose_name_plural = _("Football Fixtures")
        ordering = ['-match_date']

class MarketCategory(models.Model):
    """
    MarketCategory model to categorize different types of betting markets.
    """
    name = models.CharField(max_length=100)
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
    """
    Market model to store different types of betting markets for fixtures.
    """
    fixture = models.ForeignKey(FootballFixture, on_delete=models.CASCADE, related_name='markets')
    category = models.ForeignKey(MarketCategory, on_delete=models.CASCADE, related_name='markets')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fixture} - {self.name}"

    class Meta:
        verbose_name = _("Market")
        verbose_name_plural = _("Markets")
        ordering = ['fixture', 'category', 'name']

class MarketOutcome(models.Model):
    """
    MarketOutcome model to store possible outcomes for markets.
    """
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='outcomes')
    name = models.CharField(max_length=100)
    odds = models.DecimalField(max_digits=10, decimal_places=3)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.market} - {self.name} ({self.odds})"

    class Meta:
        verbose_name = _("Market Outcome")
        verbose_name_plural = _("Market Outcomes")
        ordering = ['market', 'name']

class Bookmaker(models.Model):
    """
    Bookmaker model to store information about betting companies.
    """
    name = models.CharField(max_length=100)
    api_bookmaker_key = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("Bookmaker")
        verbose_name_plural = _("Bookmakers")
        ordering = ['name']