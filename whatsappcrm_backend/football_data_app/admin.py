# football_data_app/admin.py
from django.contrib import admin
from .models import (
    League,
    Team,
    FootballFixture,
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
            - 'country': The country associated with the league.
            - 'season': The season associated with the league.
            - 'created_at': Timestamp of when the league was created.

        list_filter (tuple): Specifies the fields to filter by in the admin list view.
            - 'country': Filter leagues by their country.
            - 'season': Filter leagues by their season.

        search_fields (tuple): Specifies the fields to search by in the admin list view.
            - 'name': Search leagues by their name.
            - 'country': Search leagues by their country.
            - 'season': Search leagues by their season.
    """
    list_display = ('name', 'country', 'season', 'created_at')
    search_fields = ('name', 'country', 'season')
    list_filter = ('country', 'season')

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """
    TeamAdmin is a custom ModelAdmin class for managing Team model objects in the Django admin interface.

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view. 
            Includes 'name' and 'created_at'.
        search_fields (tuple): Defines the fields that can be searched in the admin interface. 
            Includes 'name'.
    """
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(FootballFixture)
class FootballFixtureAdmin(admin.ModelAdmin):
    """
    FootballFixtureAdmin is a custom Django admin class for managing FootballFixture models.

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view.
        list_filter (tuple): Defines filters for narrowing down the list view.
        search_fields (tuple): Specifies fields to search within the admin interface.
        date_hierarchy (str): Enables hierarchical navigation by date for the specified field.
    """
    list_display = ('home_team', 'away_team', 'match_date', 'status', 'league')
    list_filter = ('status', 'league', 'match_date')
    search_fields = ('home_team__name', 'away_team__name', 'league__name')
    date_hierarchy = 'match_date'

@admin.register(MarketCategory)
class MarketCategoryAdmin(admin.ModelAdmin):
    """
    MarketCategoryAdmin is a Django ModelAdmin class that customizes the admin interface
    for the MarketCategory model. It provides the following configurations:

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view.
            - 'name': The name of the market category.
            - 'created_at': Timestamp of when the market category was created.

        search_fields (tuple): Specifies the fields to include in the search functionality.
            - 'name': Allows searching by the name of the market category.
    """
    list_display = ('name', 'created_at')
    search_fields = ('name',)

@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    """
    MarketAdmin is a custom admin configuration for the Market model in the Django admin interface.

    Attributes:
        list_display (tuple): Specifies the fields to display in the admin list view. Includes fixture details, category, and status.
        list_filter (tuple): Defines the fields to filter the list view by. Includes category and status.
        search_fields (tuple): Specifies the fields to enable search functionality in the admin interface. Includes fixture event ID, home team name, away team name, and category.
    """
    list_display = ('name', 'fixture', 'category', 'is_active')
    list_filter = ('is_active', 'category')
    search_fields = ('name', 'fixture__home_team__name', 'fixture__away_team__name')

@admin.register(MarketOutcome)
class MarketOutcomeAdmin(admin.ModelAdmin):
    """
    MarketOutcomeAdmin is a custom admin configuration for the MarketOutcome model in the Django admin interface.

    Attributes:
        list_display (tuple): Specifies the fields to display in the list view of the admin interface.
            Includes 'name', 'market', 'odds', and 'is_active'.
        list_filter (tuple): Defines filters for narrowing down the list view results.
            Includes 'is_active' and 'market__category'.
        search_fields (tuple): Specifies fields to enable search functionality in the admin interface.
            Includes 'name' and 'market__name'.
    """
    list_display = ('name', 'market', 'odds', 'is_active')
    list_filter = ('is_active', 'market__category')
    search_fields = ('name', 'market__name')

