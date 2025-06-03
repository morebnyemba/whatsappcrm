# whatsappcrm_backend/football_data_app/models.py
from django.db import models
from django.utils import timezone

class FootballFixture(models.Model):
    competition_code = models.CharField(max_length=10, db_index=True)
    competition_name = models.CharField(max_length=100, null=True, blank=True)
    match_api_id = models.IntegerField(unique=True, help_text="Match ID from football-data.org")
    home_team_name = models.CharField(max_length=100)
    home_team_short_name = models.CharField(max_length=50, null=True, blank=True)
    away_team_name = models.CharField(max_length=100)
    away_team_short_name = models.CharField(max_length=50, null=True, blank=True)
    match_datetime_utc = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, db_index=True) # SCHEDULED, LIVE, FINISHED, etc.
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    winner = models.CharField(max_length=20, null=True, blank=True) # HOME_TEAM, AWAY_TEAM, DRAW
    last_api_update = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last update from the API for this match")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.home_team_name} vs {self.away_team_name} on {self.match_datetime_utc.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['match_datetime_utc']
        verbose_name = "Football Fixture"
        verbose_name_plural = "Football Fixtures"