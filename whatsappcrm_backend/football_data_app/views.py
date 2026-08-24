# whatsappcrm_backend/football_data_app/views.py
"""
Read-oriented betting API for the web dashboard.

The primary betting surface is WhatsApp; these endpoints back the dashboard's
Matches / Tickets / Wallet / summary views. All are scoped to the authenticated
user for their own wallet/tickets/transactions. Placing bets is intentionally
not exposed here — it goes through the WhatsApp guided flow which owns
validation (funds, fixture status, odds, stake limits).
"""
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import viewsets, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response

from customer_data.models import UserWallet, WalletTransaction, BetTicket
from .models import FootballFixture
from .betting_ux import _bettable_fixtures_qs
from .serializers import (
    FootballFixtureSerializer, UserWalletSerializer,
    WalletTransactionSerializer, BetTicketSerializer,
)


class FixtureViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Upcoming and LIVE, bettable fixtures with representative markets/odds."""
    serializer_class = FootballFixtureSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.query_params.get('status') == 'all':
            return (
                FootballFixture.objects
                .select_related('league', 'home_team', 'away_team')
                .prefetch_related('markets__category', 'markets__outcomes')
                .order_by('match_date')
            )
        # Default: the same "bettable right now" definition the WhatsApp
        # flows use (upcoming SCHEDULED within the browse window, or LIVE,
        # with an active market), LIVE sorted first -- previously
        # SCHEDULED-only, which silently hid every LIVE fixture from the
        # web portal even though WhatsApp already supports betting on them.
        return _bettable_fixtures_qs().prefetch_related('markets__category', 'markets__outcomes')


class WalletViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The authenticated user's wallet and its transactions."""
    serializer_class = UserWalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserWallet.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'])
    def me(self, request):
        wallet, _ = UserWallet.objects.get_or_create(user=request.user)
        return Response(self.get_serializer(wallet).data)

    @action(detail=False, methods=['get'])
    def transactions(self, request):
        wallet, _ = UserWallet.objects.get_or_create(user=request.user)
        txns = WalletTransaction.objects.filter(wallet=wallet).order_by('-created_at')[:100]
        return Response(WalletTransactionSerializer(txns, many=True).data)


class BetTicketViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The authenticated user's bet tickets (open and settled)."""
    serializer_class = BetTicketSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = (
            BetTicket.objects.filter(user=self.request.user)
            .prefetch_related(
                'bets__market_outcome__market__category',
                'bets__market_outcome__market__fixture__home_team',
                'bets__market_outcome__market__fixture__away_team',
            )
            .order_by('-created_at')
        )
        status_param = self.request.query_params.get('status')
        if status_param == 'open':
            qs = qs.filter(status__in=['PENDING', 'PLACED'])
        elif status_param == 'settled':
            qs = qs.filter(status__in=['WON', 'LOST', 'REFUNDED', 'PARTIAL_WIN'])
        return qs

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Small aggregate for the dashboard landing view."""
        user = request.user
        wallet, _ = UserWallet.objects.get_or_create(user=user)
        tickets = BetTicket.objects.filter(user=user)
        counts = tickets.aggregate(
            total=Count('id'),
            open=Count('id', filter=Q(status__in=['PENDING', 'PLACED'])),
            won=Count('id', filter=Q(status='WON')),
        )
        upcoming = FootballFixture.objects.filter(
            status=FootballFixture.FixtureStatus.SCHEDULED,
            match_date__gte=timezone.now(),
        ).count()
        return Response({
            'balance': wallet.balance,
            'tickets_total': counts['total'],
            'tickets_open': counts['open'],
            'tickets_won': counts['won'],
            'upcoming_fixtures': upcoming,
        })
