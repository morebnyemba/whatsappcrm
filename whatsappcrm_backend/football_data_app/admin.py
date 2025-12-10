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
    MarketOutcome,
    Configuration
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
    list_display = ('id','__str__', 'league', 'status', 'match_date', 'last_odds_update', 'last_score_update')
    list_filter = ('status', 'league', 'match_date')
    search_fields = ('home_team__name', 'away_team__name', 'league__name', 'api_id')
    date_hierarchy = 'match_date'
    list_select_related = ('league', 'home_team', 'away_team')
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
    list_display = ('get_fixture_representation', 'category', 'bookmaker', 'is_active', 'last_updated_odds_api')
    list_filter = ('is_active', 'category', 'bookmaker')
    search_fields = ('fixture__home_team__name', 'fixture__away_team__name', 'fixture__api_id', 'category__name', 'bookmaker__name')
    autocomplete_fields = ['fixture', 'category', 'bookmaker']
    list_select_related = ('fixture__home_team', 'fixture__away_team', 'category', 'bookmaker')
    inlines = [MarketOutcomeInline]

    def get_fixture_representation(self, obj):
        if obj.fixture:
            return str(obj.fixture)
        return "N/A"
    get_fixture_representation.short_description = 'Fixture'
    get_fixture_representation.admin_order_field = 'fixture'

@admin.register(MarketOutcome)
class MarketOutcomeAdmin(admin.ModelAdmin):
    """Admin configuration for the MarketOutcome model."""
    list_display = ('__str__', 'market', 'result_status', 'is_active')
    list_filter = ('is_active', 'result_status', 'market__category', 'market__bookmaker')
    search_fields = ('outcome_name', 'market__fixture__home_team__name', 'market__fixture__away_team__name', 'market__fixture__api_id')
    autocomplete_fields = ['market']
    list_select_related = ('market__fixture__home_team', 'market__fixture__away_team', 'market__category', 'market__bookmaker')

@admin.register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    """Admin configuration for the Configuration model."""
    list_display = ('provider_name', 'email', 'is_active', 'api_key_display', 'updated_at')
    list_filter = ('provider_name', 'is_active')
    search_fields = ('provider_name', 'email')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Provider Information', {
            'fields': ('provider_name', 'email', 'is_active')
        }),
        ('API Configuration', {
            'fields': ('api_key',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def api_key_display(self, obj):
        if obj.api_key:
            return f"********{obj.api_key[-4:]}" # Mask the API key
        return "Not Set"
    api_key_display.short_description = 'API Key (Masked)'