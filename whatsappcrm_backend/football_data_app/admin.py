# football_data_app/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    League,
    Team,
    FootballFixture,
    Bookmaker,
    MarketCategory,
    Market,
    MarketOutcome
)

@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    """Admin configuration for the League model."""
    list_display = ('name', 'api_id', 'sport_key', 'active', 'last_fetched_events')
    list_filter = ('active', 'sport_key')
    search_fields = ('name', 'api_id')
    actions = ['mark_as_active', 'mark_as_inactive']

    def mark_as_active(self, request, queryset):
        queryset.update(active=True)
    mark_as_active.short_description = "Mark selected leagues as active"

    def mark_as_inactive(self, request, queryset):
        queryset.update(active=False)
    mark_as_inactive.short_description = "Mark selected leagues as inactive"

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """Admin configuration for the Team model."""
    list_display = ('name', 'display_logo')
    search_fields = ('name',)

    def display_logo(self, obj):
        if obj.logo_url:
            return format_html('<img src="{}" width="30" height="30" />', obj.logo_url)
        return "No Logo"
    display_logo.short_description = 'Logo'

class MarketInline(admin.TabularInline):
    """
    Allows viewing and editing Markets directly within the FootballFixture admin page.
    This provides a nested view, making it easy to see all markets for a given fixture.
    """
    model = Market
    extra = 0
    fields = ('bookmaker', 'category', 'api_market_key', 'last_updated_odds_api', 'is_active')
    readonly_fields = ('last_updated_odds_api',)
    autocomplete_fields = ['bookmaker', 'category']
    show_change_link = True

@admin.register(FootballFixture)
class FootballFixtureAdmin(admin.ModelAdmin):
    """Admin configuration for the FootballFixture model."""
    list_display = ('__str__', 'league', 'status', 'match_date', 'last_odds_update', 'last_score_update')
    list_filter = ('status', 'league', 'match_date')
    search_fields = ('home_team__name', 'away_team__name', 'league__name', 'api_id')
    date_hierarchy = 'match_date'
    autocomplete_fields = ['league', 'home_team', 'away_team']
    inlines = [MarketInline]

@admin.register(Bookmaker)
class BookmakerAdmin(admin.ModelAdmin):
    """Admin configuration for the Bookmaker model."""
    list_display = ('name', 'api_bookmaker_key')
    search_fields = ('name', 'api_bookmaker_key')

@admin.register(MarketCategory)
class MarketCategoryAdmin(admin.ModelAdmin):
    """Admin configuration for the MarketCategory model."""
    list_display = ('name', 'description')
    search_fields = ('name',)

class MarketOutcomeInline(admin.TabularInline):
    """Allows viewing and editing MarketOutcomes directly within the Market admin page."""
    model = MarketOutcome
    extra = 0
    fields = ('outcome_name', 'odds', 'point_value', 'result_status', 'is_active')
    readonly_fields = ('result_status',) # Result is set by settlement tasks

@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    """Admin configuration for the Market model."""
    list_display = ('fixture_display', 'category', 'bookmaker', 'is_active', 'last_updated_odds_api')
    list_filter = ('is_active', 'category', 'bookmaker')
    search_fields = ('fixture_display__home_team__name', 'fixture_display__away_team__name', 'category__name')
    autocomplete_fields = ['fixture_display', 'category', 'bookmaker']
    inlines = [MarketOutcomeInline]

@admin.register(MarketOutcome)
class MarketOutcomeAdmin(admin.ModelAdmin):
    """Admin configuration for the MarketOutcome model."""
    list_display = ('__str__', 'market', 'result_status', 'is_active')
    list_filter = ('is_active', 'result_status', 'market__category', 'market__bookmaker')
    search_fields = ('outcome_name', 'market__fixture_display__home_team__name', 'market__fixture_display__away_team__name')
    autocomplete_fields = ['market']
    list_select_related = ('market__fixture_display', 'market__category', 'market__bookmaker')