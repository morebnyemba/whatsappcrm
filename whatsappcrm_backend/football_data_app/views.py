from django.shortcuts import render
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from .models import UserWallet, WalletTransaction, Bet, MarketOutcome
from .serializers import (
    UserWalletSerializer, WalletTransactionSerializer, BetSerializer,
    PlaceBetSerializer, FootballFixtureSerializer
)

# Create your views here.

class WalletViewSet(viewsets.ModelViewSet):
    serializer_class = UserWalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserWallet.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'])
    def transactions(self, request):
        transactions = WalletTransaction.objects.filter(wallet=request.user.wallet)
        serializer = WalletTransactionSerializer(transactions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def deposit(self, request):
        amount = request.data.get('amount')
        if not amount or float(amount) <= 0:
            return Response(
                {"error": "Invalid amount"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            with transaction.atomic():
                wallet = request.user.wallet
                wallet.add_funds(amount)
                WalletTransaction.objects.create(
                    wallet=wallet,
                    amount=amount,
                    transaction_type='DEPOSIT',
                    description="Deposit to wallet"
                )
            return Response(self.get_serializer(wallet).data)
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

class BetViewSet(viewsets.ModelViewSet):
    serializer_class = BetSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Bet.objects.filter(user=self.request.user)

    @action(detail=False, methods=['post'])
    def place_bet(self, request):
        serializer = PlaceBetSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                market_outcome = MarketOutcome.objects.get(id=serializer.validated_data['market_outcome_id'])
                bet = Bet.objects.create(
                    user=request.user,
                    market_outcome=market_outcome,
                    amount=serializer.validated_data['amount']
                )
                bet.place_bet()
                return Response(BetSerializer(bet).data)
        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'])
    def bet_details(self, request, pk=None):
        bet = self.get_object()
        return Response(BetSerializer(bet).data)
