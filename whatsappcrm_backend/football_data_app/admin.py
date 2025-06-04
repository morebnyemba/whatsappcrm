from django.contrib import admin
from .models import (
    League, Team, FootballFixture, Bookmaker,
    MarketCategory, Market, MarketOutcome,
    UserWallet, Transaction, Bet, BetSelection
)

# Inline Admin classes for related models

class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_team_id', 'country', 'code')
    search_fields = ('name', 'api_team_id', 'code')
    list_filter = ('country',)
admin.site.register(Team, TeamAdmin)

class LeagueAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_league_id', 'country')
    search_fields = ('name', 'api_league_id')
    list_filter = ('country',)
admin.site.register(League, LeagueAdmin)


class MarketOutcomeInline(admin.TabularInline): # Or admin.StackedInline
    model = MarketOutcome
    extra = 1 # Number of empty forms to display
    readonly_fields = ('result_status',) # Result status is usually set programmatically
    fields = ('outcome_name', 'odds', 'is_suspended', 'result_status')

class MarketAdmin(admin.ModelAdmin):
    list_display = ('fixture_display', 'bookmaker', 'category', 'market_parameter', 'is_active', 'last_updated_odds_api')
    search_fields = ('fixture__match_api_id', 'fixture__home_team__name', 'fixture__away_team__name', 'bookmaker__name', 'category__name')
    list_filter = ('category', 'bookmaker', 'is_active', 'fixture__league')
    inlines = [MarketOutcomeInline]
    autocomplete_fields = ['fixture', 'bookmaker', 'category'] # For easier selection

    def fixture_display(self, obj):
        return str(obj.fixture)
    fixture_display.short_description = "Fixture"

admin.site.register(Market, MarketAdmin)

class MarketOutcomeAdmin(admin.ModelAdmin):
    list_display = ('market_info', 'outcome_name', 'odds', 'result_status', 'is_suspended')
    search_fields = ('market__fixture__match_api_id', 'outcome_name', 'market__category__name')
    list_filter = ('result_status', 'is_suspended', 'market__category', 'market__bookmaker')
    list_editable = ('odds', 'is_suspended') # Allow direct editing of odds and suspension status
    readonly_fields = ('market',) # Usually set via Market inline

    def market_info(self, obj):
        return f"{obj.market.category.name} ({obj.market.market_parameter if obj.market.market_parameter else ''}) - FixID: {obj.market.fixture.match_api_id}"
    market_info.short_description = "Market"

admin.site.register(MarketOutcome, MarketOutcomeAdmin)


class MarketInlineForFixture(admin.TabularInline):
    model = Market
    extra = 0
    fields = ('bookmaker', 'category', 'market_parameter', 'is_active', 'last_updated_odds_api')
    readonly_fields = ('last_updated_odds_api',)
    show_change_link = True
    verbose_name_plural = "Odds Markets for this Fixture"

class FootballFixtureAdmin(admin.ModelAdmin):
    list_display = ('match_api_id', 'league', 'home_team', 'away_team', 'match_date', 'status_short', 'home_team_score', 'away_team_score', 'is_result_confirmed')
    search_fields = ('match_api_id', 'home_team__name', 'away_team__name', 'league__name')
    list_filter = ('league', 'status_short', 'is_result_confirmed', 'match_date')
    date_hierarchy = 'match_date'
    ordering = ('-match_date',)
    list_editable = ('status_short', 'home_team_score', 'away_team_score', 'is_result_confirmed')
    readonly_fields = ('api_fixture_timestamp', 'last_updated_from_api')
    autocomplete_fields = ['league', 'home_team', 'away_team']
    inlines = [MarketInlineForFixture]
    fieldsets = (
        (None, {
            'fields': ('match_api_id', 'league', 'round', 'match_date', 'api_fixture_timestamp')
        }),
        ('Teams & Venue', {
            'fields': ('home_team', 'away_team', 'venue_name', 'referee')
        }),
        ('Status & Score', {
            'fields': ('status_short', 'status_long', 'home_team_score', 'away_team_score',
                       'halftime_home_score', 'halftime_away_score',
                       'extratime_home_score', 'extratime_away_score',
                       'penalty_home_score', 'penalty_away_score',
                       'is_result_confirmed', 'last_updated_from_api')
        }),
    )
admin.site.register(FootballFixture, FootballFixtureAdmin)

class BookmakerAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_bookmaker_id')
    search_fields = ('name', 'api_bookmaker_id')
admin.site.register(Bookmaker, BookmakerAdmin)

class MarketCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)
admin.site.register(MarketCategory, MarketCategoryAdmin)


# Betting System Models
class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 0
    fields = ('transaction_type', 'amount', 'timestamp', 'description', 'related_bet_id', 'balance_before', 'balance_after')
    readonly_fields = ('timestamp', 'balance_before', 'balance_after')
    can_delete = False
    show_change_link = True

class UserWalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'bonus_balance', 'last_updated')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('last_updated',)
    inlines = [TransactionInline]
admin.site.register(UserWallet, UserWalletAdmin)

class TransactionAdmin(admin.ModelAdmin):
    list_display = ('wallet_user', 'transaction_type', 'amount', 'timestamp', 'related_bet_id')
    search_fields = ('wallet__user__username', 'related_bet_id', 'description')
    list_filter = ('transaction_type', 'timestamp')
    date_hierarchy = 'timestamp'
    readonly_fields = ('wallet', 'timestamp', 'balance_before', 'balance_after') # Wallet usually shouldn't be changed here

    def wallet_user(self, obj):
        return obj.wallet.user.username
    wallet_user.short_description = 'User'
    wallet_user.admin_order_field = 'wallet__user'


admin.site.register(Transaction, TransactionAdmin)

class BetSelectionInline(admin.TabularInline):
    model = BetSelection
    extra = 0
    fields = ('market_outcome_info', 'odds_at_placement', 'result_status', 'fixture_description', 'market_description', 'outcome_description')
    readonly_fields = ('market_outcome_info', 'fixture_description', 'market_description', 'outcome_description') # These are for display
    autocomplete_fields = ['market_outcome'] # If you want to select them directly, but usually created with Bet
    show_change_link = True

    def market_outcome_info(self, obj):
        if obj.market_outcome:
            return f"{obj.market_outcome.market.category.name}: {obj.market_outcome.outcome_name} @ {obj.market_outcome.odds}"
        return "N/A"
    market_outcome_info.short_description = "Market Outcome"


class BetAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'stake', 'total_odds', 'potential_winnings', 'actual_winnings', 'bet_type', 'status', 'placed_at', 'settled_at')
    search_fields = ('id__iexact', 'user__username', 'user__email')
    list_filter = ('status', 'bet_type', 'placed_at', 'settled_at', 'user')
    date_hierarchy = 'placed_at'
    readonly_fields = ('id', 'user', 'placed_at', 'settled_at', 'potential_winnings', 'actual_winnings') # Some fields should be immutable after creation or set by system
    inlines = [BetSelectionInline]
    fieldsets = (
        (None, {'fields': ('id', 'user', 'status', 'bet_type')}),
        ('Financials', {'fields': ('stake', 'total_odds', 'potential_winnings', 'actual_winnings')}),
        ('Timestamps', {'fields': ('placed_at', 'settled_at')}),
    )
admin.site.register(Bet, BetAdmin)

class BetSelectionAdmin(admin.ModelAdmin):
    list_display = ('bet_id_display', 'market_outcome_display', 'odds_at_placement', 'result_status')
    search_fields = ('bet__id__iexact', 'bet__user__username', 'market_outcome__outcome_name')
    list_filter = ('result_status', 'market_outcome__market__category', 'market_outcome__market__bookmaker')
    readonly_fields = ('bet', 'market_outcome') # Usually not changed directly here
    list_editable = ('result_status',) # Allow admin to manually override selection result if needed

    def bet_id_display(self, obj):
        return obj.bet.id
    bet_id_display.short_description = "Bet ID"

    def market_outcome_display(self, obj):
        if obj.market_outcome:
            mo = obj.market_outcome
            fix = mo.market.fixture
            return f"{fix.home_team.name if fix.home_team else 'N/A'} vs {fix.away_team.name if fix.away_team else 'N/A'} - {mo.market.category.name}: {mo.outcome_name}"
        return "N/A"
    market_outcome_display.short_description = "Selection"

admin.site.register(BetSelection, BetSelectionAdmin)

# If you had an FixtureEvent model and wanted to register it:
# class FixtureEventAdmin(admin.ModelAdmin):
#     list_display = ('fixture', 'event_type', 'event_detail', 'team', 'player_name', 'event_minute')
#     search_fields = ('fixture__match_api_id', 'player_name', 'team__name')
#     list_filter = ('event_type', 'fixture__league')
# admin.site.register(FixtureEvent, FixtureEventAdmin)

