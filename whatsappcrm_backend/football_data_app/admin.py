# football_data_app/admin.py
from django.contrib import admin
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
    """
    LeagueAdmin is a custom admin configuration for the League model in the Django admin interface.

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view.
            - 'name': The name of the league.
            - 'sport_key': The key identifying the sport associated with the league.
            - 'sport_title': The title of the sport associated with the league.
            - 'active': Indicates whether the league is active.
            - 'last_fetched_events': Timestamp of the last fetched events for the league.
            - 'updated_at': Timestamp of the last update to the league.

        list_filter (tuple): Specifies the fields to filter by in the admin list view.
            - 'active': Filter leagues by their active status.
            - 'sport_key': Filter leagues by their sport key.

        search_fields (tuple): Specifies the fields to search by in the admin list view.
            - 'name': Search leagues by their name.
            - 'sport_key': Search leagues by their sport key.
            - 'sport_title': Search leagues by their sport title.

        readonly_fields (tuple): Specifies the fields that are read-only in the admin form view.
            - 'created_at': Timestamp of when the league was created.
            - 'updated_at': Timestamp of the last update to the league.
            - 'last_fetched_events': Timestamp of the last fetched events for the league.
    """
    list_display = ('name', 'sport_key', 'sport_title', 'active', 'last_fetched_events', 'updated_at')
    list_filter = ('active', 'sport_key')
    search_fields = ('name', 'sport_key', 'sport_title')
    readonly_fields = ('created_at', 'updated_at', 'last_fetched_events')

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """
    TeamAdmin is a custom ModelAdmin class for managing Team model objects in the Django admin interface.

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view. 
            Includes 'name', 'created_at', and 'updated_at'.
        search_fields (tuple): Defines the fields that can be searched in the admin interface. 
            Includes 'name'.
        readonly_fields (tuple): Specifies the fields that are read-only in the admin interface. 
            Includes 'created_at' and 'updated_at'.
    """
    list_display = ('name', 'created_at', 'updated_at')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')

class MarketOutcomeInline(admin.TabularInline): # Or admin.StackedInline for a different layout
    """
    MarketOutcomeInline is a Django admin inline class used to manage MarketOutcome objects 
    within the admin interface. It provides a tabular layout for displaying and editing 
    related MarketOutcome instances.

    Attributes:
        model (MarketOutcome): Specifies the model associated with this inline.
        extra (int): Determines the number of empty forms to display for adding new instances. 
                     Set to 0 to disable empty forms.
        fields (tuple): Defines the fields to display in the inline form. Includes 'outcome_name', 
                        'odds', 'point_value', 'result_status', and 'updated_at'.
        readonly_fields (tuple): Specifies fields that are read-only in the inline form. 
                                 Includes 'updated_at'.
        ordering (tuple): Specifies the default ordering of the inline instances. 
                          Ordered by 'outcome_name'.
    """
    model = MarketOutcome
    extra = 0 # Number of empty forms to display
    fields = ('outcome_name', 'odds', 'point_value', 'result_status', 'updated_at')
    readonly_fields = ('updated_at',)
    ordering = ('outcome_name',)

@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    """
    MarketAdmin is a custom admin configuration for the Market model in the Django admin interface.

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view. Includes fixture details, bookmaker, category, API market key, and timestamps.
        list_filter (tuple): Defines the fields to filter the list view by. Includes bookmaker, category, API market key, and league associated with the fixture.
        search_fields (tuple): Specifies the fields to enable search functionality in the admin interface. Includes fixture event ID, home team name, away team name, bookmaker name, and API market key.
        readonly_fields (tuple): Lists fields that are read-only in the admin interface. Includes created_at, updated_at, and last_updated_odds_api.
        inlines (list): Specifies inline models to be displayed within the admin interface. Includes MarketOutcomeInline.
        autocomplete_fields (list): Enables autocomplete functionality for specified fields. Includes fixture_display, bookmaker, and category.
    """
    list_display = ('fixture_display', 'bookmaker', 'category', 'api_market_key', 'last_updated_odds_api', 'updated_at')
    list_filter = ('bookmaker', 'category', 'api_market_key', 'fixture_display__league')
    search_fields = ('fixture_display__event_api_id', 'fixture_display__home_team_name', 'fixture_display__away_team_name', 'bookmaker__name', 'api_market_key')
    readonly_fields = ('created_at', 'updated_at', 'last_updated_odds_api')
    inlines = [MarketOutcomeInline]
    autocomplete_fields = ['fixture_display', 'bookmaker', 'category']

class MarketInline(admin.TabularInline): # Or admin.StackedInline
    """
    MarketInline is a Django admin inline class used to manage the Market model within a parent model's admin interface.
    It provides a tabular or stacked layout for editing related Market instances.

    Attributes:
        model (Market): Specifies the model to be managed in the inline.
        extra (int): Number of empty forms to display for adding new Market instances. Default is 0.
        fields (tuple): Specifies the fields to display in the inline form.
        readonly_fields (tuple): Specifies the fields that are read-only in the inline form.
        autocomplete_fields (list): Enables autocomplete functionality for specified foreign key fields.
        show_change_link (bool): Allows navigation to the Market change page directly from the inline form.
    """
    model = Market
    extra = 0
    fields = ('bookmaker', 'category', 'api_market_key', 'last_updated_odds_api', 'updated_at')
    readonly_fields = ('last_updated_odds_api', 'updated_at')
    autocomplete_fields = ['bookmaker', 'category']
    show_change_link = True # Allows navigating to the Market change page from the inline

@admin.register(FootballFixture)
class FootballFixtureAdmin(admin.ModelAdmin):
    """
    FootballFixtureAdmin is a custom Django admin class for managing FootballFixture models.

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view.
        list_filter (tuple): Defines filters for narrowing down the list view.
        search_fields (tuple): Specifies fields to search within the admin interface.
        readonly_fields (tuple): Fields that are read-only in the admin interface.
        date_hierarchy (str): Enables hierarchical navigation by date for the specified field.
        inlines (list): Specifies inline models to display related data directly on the fixture page.
        autocomplete_fields (list): Enables autocomplete functionality for specified foreign key fields.
        fieldsets (tuple): Organizes fields into logical sections in the admin form.

    Fieldsets:
        - Default: Contains general fields like event_api_id, league, sport_key, commence_time, and completed.
        - Teams: Groups fields related to home and away teams.
        - Scores & Updates: Includes fields for scores and last update timestamps.
        - Timestamps: Collapsible section for created_at and updated_at fields.
    """
    list_display = (
        'event_api_id',
        'league',
        'home_team_name',
        'away_team_name',
        'commence_time',
        'home_team_score',
        'away_team_score',
        'completed',
        'last_odds_update',
        'last_score_update'
    )
    list_filter = ('completed', 'league', 'commence_time', 'sport_key')
    search_fields = ('event_api_id', 'home_team_name', 'away_team_name', 'league__name', 'sport_key')
    readonly_fields = ('created_at', 'updated_at', 'last_odds_update', 'last_score_update')
    date_hierarchy = 'commence_time'
    inlines = [MarketInline] # Display markets directly on the fixture page
    autocomplete_fields = ['league', 'home_team', 'away_team']
    fieldsets = (
        (None, {
            'fields': ('event_api_id', 'league', 'sport_key', 'commence_time', 'completed')
        }),
        ('Teams', {
            'fields': (('home_team_name', 'home_team'), ('away_team_name', 'away_team'))
        }),
        ('Scores & Updates', {
            'fields': (('home_team_score', 'away_team_score'), 'last_odds_update', 'last_score_update')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',) # Collapsible section
        }),
    )


@admin.register(Bookmaker)
class BookmakerAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_bookmaker_key', 'updated_at')
    search_fields = ('name', 'api_bookmaker_key')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(MarketCategory)
class MarketCategoryAdmin(admin.ModelAdmin):
    """
    MarketCategoryAdmin is a Django ModelAdmin class that customizes the admin interface
    for the MarketCategory model. It provides the following configurations:

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view.
            - 'name': The name of the market category.
            - 'description': A brief description of the market category.

        search_fields (tuple): Specifies the fields to include in the search functionality.
            - 'name': Allows searching by the name of the market category.
    """
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(MarketOutcome)
class MarketOutcomeAdmin(admin.ModelAdmin):
    """
    MarketOutcomeAdmin is a custom admin configuration for the MarketOutcome model in the Django admin interface.

    Attributes:
        list_display (tuple): Specifies the fields to display in the list view of the admin interface.
            Includes 'market', 'outcome_name', 'odds', 'point_value', 'result_status', and 'updated_at'.
        list_filter (tuple): Defines filters for narrowing down the list view results.
            Includes 'result_status', 'market__category', 'market__bookmaker', and 'market__fixture_display__league'.
        search_fields (tuple): Specifies fields to enable search functionality in the admin interface.
            Includes 'outcome_name', 'market__fixture_display__event_api_id', 
            'market__fixture_display__home_team_name', 'market__fixture_display__away_team_name', 
            and 'market__bookmaker__name'.
        readonly_fields (tuple): Defines fields that are read-only in the admin interface.
            Includes 'created_at' and 'updated_at'.
        autocomplete_fields (list): Specifies fields that use autocomplete functionality for easier selection.
            Includes 'market'.
        list_editable (tuple): Specifies fields that can be edited directly in the list view.
            Includes 'result_status'.
    """
    list_display = ('market', 'outcome_name', 'odds', 'point_value', 'result_status', 'updated_at')
    list_filter = ('result_status', 'market__category', 'market__bookmaker', 'market__fixture_display__league')
    search_fields = (
        'outcome_name',
        'market__fixture_display__event_api_id',
        'market__fixture_display__home_team_name',
        'market__fixture_display__away_team_name',
        'market__bookmaker__name'
    )
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ['market']
    list_editable = ('result_status',) # Allow editing result_status directly in the list view

