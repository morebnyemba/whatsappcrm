# whatsappcrm_backend/football_data_app/serializers.py
"""
Serializers for the betting web dashboard API.

These match the real data model: fixtures/markets/outcomes live in
football_data_app; wallet/transactions/tickets/bets live in customer_data.
They are read-oriented (the web dashboard is a read surface; placing bets is
done through the WhatsApp flow, which owns validation).
"""
from rest_framework import serializers

from customer_data.models import UserWallet, WalletTransaction, BetTicket, Bet
from .models import FootballFixture, MarketOutcome


class MarketOutcomeSerializer(serializers.ModelSerializer):
    odds = serializers.DecimalField(max_digits=10, decimal_places=3, coerce_to_string=False)

    class Meta:
        model = MarketOutcome
        fields = ['id', 'outcome_name', 'odds', 'point_value', 'result_status']


class FixtureMarketSerializer(serializers.Serializer):
    """One representative market per category with its outcomes."""
    category = serializers.CharField()
    api_market_key = serializers.CharField()
    outcomes = MarketOutcomeSerializer(many=True)


class FootballFixtureSerializer(serializers.ModelSerializer):
    league = serializers.CharField(source='league.name', read_only=True)
    home_team = serializers.CharField(source='home_team.name', read_only=True)
    away_team = serializers.CharField(source='away_team.name', read_only=True)
    markets = serializers.SerializerMethodField()
    prediction = serializers.SerializerMethodField()

    class Meta:
        model = FootballFixture
        fields = [
            'id', 'league', 'home_team', 'away_team', 'match_date', 'status',
            'home_team_score', 'away_team_score', 'elapsed_minutes', 'markets', 'prediction',
        ]

    def get_prediction(self, obj):
        pred = getattr(obj, 'prediction', None)
        if pred is None:
            return None
        return {
            'prob_home': round(pred.prob_home, 4),
            'prob_draw': round(pred.prob_draw, 4),
            'prob_away': round(pred.prob_away, 4),
            'favored': pred.favored_side,
            'method': pred.method,
            'data_points': pred.data_points,
        }

    def get_markets(self, obj):
        # One representative (most recently updated) active market per category,
        # so displayed odds correspond to real outcome rows.
        by_category = {}
        for market in obj.markets.filter(is_active=True).select_related('category').prefetch_related('outcomes').order_by('-last_updated_odds_api'):
            by_category.setdefault(market.category.name, market)
        data = []
        for name, market in by_category.items():
            outcomes = [o for o in market.outcomes.all() if o.is_active]
            if not outcomes:
                continue
            data.append({
                'category': name,
                'api_market_key': market.api_market_key,
                'outcomes': MarketOutcomeSerializer(outcomes, many=True).data,
            })
        return data


class UserWalletSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, coerce_to_string=False)

    class Meta:
        model = UserWallet
        fields = ['id', 'balance', 'updated_at']
        read_only_fields = fields


class WalletTransactionSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, coerce_to_string=False)

    class Meta:
        model = WalletTransaction
        fields = ['id', 'amount', 'transaction_type', 'description', 'status',
                  'payment_method', 'created_at']
        read_only_fields = fields


class BetSerializer(serializers.ModelSerializer):
    fixture = serializers.SerializerMethodField()
    market = serializers.CharField(source='market_outcome.market.category.name', read_only=True)
    outcome = serializers.CharField(source='market_outcome.outcome_name', read_only=True)
    odds = serializers.DecimalField(source='market_outcome.odds', max_digits=10, decimal_places=3, coerce_to_string=False, read_only=True)

    class Meta:
        model = Bet
        fields = ['id', 'fixture', 'market', 'outcome', 'odds', 'amount',
                  'potential_winnings', 'status']
        read_only_fields = fields

    def get_fixture(self, obj):
        fx = obj.market_outcome.market.fixture
        return f"{fx.home_team.name} vs {fx.away_team.name}"


class BetTicketSerializer(serializers.ModelSerializer):
    bets = BetSerializer(many=True, read_only=True)
    bet_type_display = serializers.CharField(source='get_bet_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = BetTicket
        fields = ['id', 'total_stake', 'potential_winnings', 'total_odds',
                  'status', 'status_display', 'bet_type', 'bet_type_display',
                  'created_at', 'bets']
        read_only_fields = fields
