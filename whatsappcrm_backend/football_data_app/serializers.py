from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from .models import UserWallet, WalletTransaction, Bet, MarketOutcome, Market, FootballFixture

class UserWalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserWallet
        fields = ['id', 'balance', 'created_at', 'updated_at']
        read_only_fields = ['balance', 'created_at', 'updated_at']

class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = ['id', 'amount', 'transaction_type', 'description', 'created_at']
        read_only_fields = ['created_at']

class MarketOutcomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketOutcome
        fields = ['id', 'name', 'odds', 'result']

class MarketSerializer(serializers.ModelSerializer):
    outcomes = MarketOutcomeSerializer(many=True, read_only=True)
    
    class Meta:
        model = Market
        fields = ['id', 'name', 'outcomes']

class FootballFixtureSerializer(serializers.ModelSerializer):
    markets = MarketSerializer(many=True, read_only=True)
    
    class Meta:
        model = FootballFixture
        fields = ['id', 'home_team', 'away_team', 'commence_time', 'status', 'markets']

class BetSerializer(serializers.ModelSerializer):
    market_outcome = MarketOutcomeSerializer(read_only=True)
    fixture = FootballFixtureSerializer(source='market_outcome.market.fixture', read_only=True)
    
    class Meta:
        model = Bet
        fields = ['id', 'amount', 'odds', 'potential_winnings', 'status', 'market_outcome', 'fixture', 'created_at']
        read_only_fields = ['odds', 'potential_winnings', 'status', 'created_at']

class PlaceBetSerializer(serializers.Serializer):
    market_outcome_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)

    def validate(self, data):
        market_outcome = MarketOutcome.objects.get(id=data['market_outcome_id'])
        fixture = market_outcome.market.fixture
        
        # Check if fixture is open for betting
        if fixture.status != 'OPEN':
            raise serializers.ValidationError("This fixture is not open for betting")
            
        # Check if user has sufficient funds
        user = self.context['request'].user
        if user.wallet.balance < data['amount']:
            raise serializers.ValidationError("Insufficient funds")
            
        return data 