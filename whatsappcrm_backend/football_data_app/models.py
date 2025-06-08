# football_data_app/models.py
from django.db import models
from django.utils import timezone

class League(models.Model):
    name = models.CharField(max_length=255)
    sport_key = models.CharField(max_length=100, unique=True, db_index=True)
    sport_title = models.CharField(max_length=255, blank=True, null=True)
    active = models.BooleanField(default=True)
    last_fetched_events = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or self.sport_title or self.sport_key

class Team(models.Model):
    name = models.CharField(max_length=255, unique=True)
    # Add any other team-specific fields you need
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @classmethod
    def get_or_create_team(cls, team_name):
        """Gets or creates a team by name."""
        team, created = cls.objects.get_or_create(name=team_name)
        return team

class FootballFixture(models.Model):
    event_api_id = models.CharField(max_length=100, unique=True, db_index=True)
    league = models.ForeignKey(League, related_name='fixtures', on_delete=models.CASCADE)
    sport_key = models.CharField(max_length=100, db_index=True)
    commence_time = models.DateTimeField(db_index=True)
    
    # Store team names directly from API, but also link to Team model
    home_team_name = models.CharField(max_length=255)
    away_team_name = models.CharField(max_length=255)
    home_team = models.ForeignKey(Team, related_name='home_fixtures', on_delete=models.SET_NULL, null=True, blank=True)
    away_team = models.ForeignKey(Team, related_name='away_fixtures', on_delete=models.SET_NULL, null=True, blank=True)

    home_team_score = models.IntegerField(null=True, blank=True)
    away_team_score = models.IntegerField(null=True, blank=True)
    
    completed = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('STARTED', 'Started'),
            ('COMPLETED', 'Completed'),
            ('CANCELLED', 'Cancelled'),
        ],
        default='PENDING',
        db_index=True
    )
    last_odds_update = models.DateTimeField(null=True, blank=True)
    last_score_update = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['commence_time']

    def __str__(self):
        return f"{self.home_team_name} vs {self.away_team_name} ({self.commence_time.strftime('%Y-%m-%d %H:%M')})"

    def save(self, *args, **kwargs):
        # Automatically link to Team instances if names are provided
        if self.home_team_name and not self.home_team_id:
            self.home_team = Team.get_or_create_team(self.home_team_name)
        if self.away_team_name and not self.away_team_id:
            self.away_team = Team.get_or_create_team(self.away_team_name)
        super().save(*args, **kwargs)


class Bookmaker(models.Model):
    api_bookmaker_key = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    last_update_from_api = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class MarketCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Market Categories"


class Market(models.Model):
    fixture_display = models.ForeignKey(FootballFixture, related_name='markets', on_delete=models.CASCADE)
    bookmaker = models.ForeignKey(Bookmaker, related_name='markets', on_delete=models.CASCADE)
    category = models.ForeignKey(MarketCategory, related_name='markets', on_delete=models.CASCADE)
    api_market_key = models.CharField(max_length=100, db_index=True)
    market_parameter = models.CharField(max_length=50, blank=True, null=True) # Kept for potential use, but often derived from outcome
    last_updated_odds_api = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('fixture_display', 'bookmaker', 'api_market_key')
        ordering = ['fixture_display', 'bookmaker', 'category']

    def __str__(self):
        return f"{self.fixture_display} - {self.bookmaker} - {self.api_market_key}"

class MarketOutcome(models.Model):
    market = models.ForeignKey(Market, related_name='outcomes', on_delete=models.CASCADE)
    outcome_name = models.CharField(max_length=255)
    odds = models.DecimalField(max_digits=10, decimal_places=3)
    point_value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    RESULT_CHOICES = [
        ('PENDING', 'Pending'),
        ('WON', 'Won'),
        ('LOST', 'Lost'),
        ('VOID', 'Void'),
        ('HALF_WON', 'Half Won'),
        ('HALF_LOST', 'Half Lost'),
        ('PUSH', 'Push'),
    ]
    result_status = models.CharField(max_length=15, choices=RESULT_CHOICES, default='PENDING', db_index=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('market', 'outcome_name', 'point_value')
        ordering = ['market', 'outcome_name']

    def __str__(self):
        return f"{self.market} - {self.outcome_name}: {self.odds}"