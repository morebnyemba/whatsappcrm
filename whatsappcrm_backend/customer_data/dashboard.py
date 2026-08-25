# whatsappcrm_backend/customer_data/dashboard.py
"""
Operator KPIs for the admin dashboard.

The default Django/Jazzmin index is just a list of models, which tells an
operator nothing about the state of the business. This assembles the handful
of numbers someone actually opens the admin to check: what needs approving,
what's live right now, and how today is going.

Every figure is a cheap aggregate, and the queries line up with the indexes
added for the betting hot paths (ticket_status_idx, fixture_status_date_idx),
so rendering this doesn't put meaningful load on the DB.
"""
import logging
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

OPEN_TICKET_STATUSES = ('PENDING', 'PLACED')


def _money(value):
    return value if value is not None else Decimal('0.00')


def get_dashboard_stats():
    """Return the dashboard's KPI payload.

    Deliberately defensive: the admin index must still render if one app is
    missing or a query fails, so a failure here degrades to an empty dict
    rather than 500-ing the whole admin.
    """
    try:
        return _collect()
    except Exception:
        logger.exception("Admin dashboard stats failed to load; rendering without them.")
        return {}


def _collect():
    from django.contrib.auth import get_user_model
    from football_data_app.models import FootballFixture
    from .models import BetTicket, UserWallet, WalletTransaction, PendingWithdrawal

    User = get_user_model()
    now = timezone.now()
    today_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)

    # --- needs attention -------------------------------------------------
    withdrawals = PendingWithdrawal.objects.aggregate(n=Count('id'), total=Sum('amount'))
    pending_withdrawal_count = withdrawals['n'] or 0
    pending_withdrawal_total = _money(withdrawals['total'])

    try:
        from referrals.models import AgentApplication
        pending_agent_applications = AgentApplication.objects.filter(
            status=AgentApplication.Status.PENDING).count()
    except Exception:
        pending_agent_applications = 0

    # Finished matches whose tickets haven't settled yet -- the signal that
    # the settlement pipeline has stalled.
    unsettled_finished = BetTicket.objects.filter(
        status__in=OPEN_TICKET_STATUSES,
        bets__market_outcome__market__fixture__status=FootballFixture.FixtureStatus.FINISHED,
    ).distinct().count()

    # --- live right now --------------------------------------------------
    live_matches = FootballFixture.objects.filter(
        status=FootballFixture.FixtureStatus.LIVE).count()

    open_tickets = BetTicket.objects.filter(status__in=OPEN_TICKET_STATUSES).aggregate(
        n=Count('id'), stake=Sum('total_stake'), exposure=Sum('potential_winnings'))
    open_ticket_count = open_tickets['n'] or 0
    open_stake = _money(open_tickets['stake'])
    # What the book would owe if every open ticket won -- the operator's
    # worst-case liability, which is the number that actually matters.
    exposure = _money(open_tickets['exposure'])

    # --- today -----------------------------------------------------------
    def _today_sum(txn_type):
        return _money(WalletTransaction.objects.filter(
            transaction_type=txn_type, created_at__gte=today_start,
            status='COMPLETED',
        ).aggregate(total=Sum('amount'))['total'])

    # Stakes are stored as negative amounts (money leaving the wallet).
    stakes_today = abs(_today_sum('BET_PLACED'))
    payouts_today = _today_sum('BET_WON')
    deposits_today = _today_sum('DEPOSIT')
    gross_today = stakes_today - payouts_today

    new_players_today = User.objects.filter(date_joined__gte=today_start).count()
    player_float = _money(UserWallet.objects.aggregate(total=Sum('balance'))['total'])

    return {
        'pending_withdrawal_count': pending_withdrawal_count,
        'pending_withdrawal_total': pending_withdrawal_total,
        'pending_agent_applications': pending_agent_applications,
        'unsettled_finished': unsettled_finished,
        'needs_attention': bool(
            pending_withdrawal_count or pending_agent_applications or unsettled_finished),

        'live_matches': live_matches,
        'open_ticket_count': open_ticket_count,
        'open_stake': open_stake,
        'exposure': exposure,

        'stakes_today': stakes_today,
        'payouts_today': payouts_today,
        'gross_today': gross_today,
        'gross_today_positive': gross_today >= 0,
        'deposits_today': deposits_today,
        'new_players_today': new_players_today,
        'player_float': player_float,
    }


def unfold_dashboard_callback(request, context):
    """Inject the operator KPIs into Unfold's admin index.

    Wired up as UNFOLD["DASHBOARD_CALLBACK"]. Unfold calls this with the
    admin index context and expects the (mutated) context back; the KPI
    cards themselves are rendered by templates/admin/index.html.

    Shaped as groups of cards here rather than in the template so the
    template stays declarative and the "which cards, in what order, with
    what emphasis" decisions live in Python where they can be tested.
    """
    from django.urls import reverse

    stats = get_dashboard_stats()
    if not stats:
        context["kpi_groups"] = []
        return context

    groups = []

    attention = []
    if stats.get("pending_withdrawal_count"):
        attention.append({
            # Amount leads: it's what decides how urgently to act.
            "value": f"${stats['pending_withdrawal_total']:,.2f}",
            "label": "Withdrawals awaiting approval",
            "sub": f"{stats['pending_withdrawal_count']} request(s)",
            "url": reverse("admin:customer_data_pendingwithdrawal_changelist"),
            "tone": "warning",
            "icon": "payments",
        })
    if stats.get("pending_agent_applications"):
        attention.append({
            "value": stats["pending_agent_applications"],
            "label": "Agent applications pending",
            "sub": "awaiting review",
            "url": reverse("admin:referrals_agentapplication_changelist") + "?status__exact=PENDING",
            "tone": "info",
            "icon": "person_add",
        })
    if stats.get("unsettled_finished"):
        attention.append({
            "value": stats["unsettled_finished"],
            "label": "Open tickets on finished matches",
            "sub": "settlement may be stalled",
            "url": reverse("admin:customer_data_betticket_changelist") + "?status__exact=PLACED",
            "tone": "danger",
            "icon": "warning",
        })
    if attention:
        groups.append({"title": "Needs your attention", "icon": "notifications", "cards": attention})

    groups.append({
        "title": "Live position",
        "icon": "sensors",
        "cards": [
            {"value": stats["live_matches"], "label": "Matches live now", "sub": "in play",
             "url": reverse("admin:football_data_app_footballfixture_changelist") + "?status__exact=LIVE",
             "tone": "danger", "icon": "cell_tower"},
            {"value": stats["open_ticket_count"], "label": "Open tickets",
             "sub": f"${stats['open_stake']:,.2f} staked",
             "url": reverse("admin:customer_data_betticket_changelist") + "?status__exact=PLACED",
             "tone": "default", "icon": "confirmation_number"},
            {"value": f"${stats['exposure']:,.2f}", "label": "Exposure",
             "sub": "if every open ticket won", "tone": "warning", "icon": "balance"},
            {"value": f"${stats['player_float']:,.2f}", "label": "Player balances held",
             "sub": "total wallet float",
             "url": reverse("admin:customer_data_userwallet_changelist"),
             "tone": "default", "icon": "account_balance_wallet"},
        ],
    })

    groups.append({
        "title": "Today",
        "icon": "trending_up",
        "cards": [
            {"value": f"${stats['stakes_today']:,.2f}", "label": "Stakes taken",
             "sub": "money in", "tone": "success", "icon": "south"},
            {"value": f"${stats['payouts_today']:,.2f}", "label": "Payouts",
             "sub": "money out", "tone": "danger", "icon": "north"},
            {"value": f"${stats['gross_today']:,.2f}", "label": "Gross",
             "sub": "stakes minus payouts",
             "tone": "success" if stats["gross_today_positive"] else "danger", "icon": "savings"},
            {"value": stats["new_players_today"], "label": "New players",
             "sub": f"${stats['deposits_today']:,.2f} deposited",
             "tone": "info", "icon": "person_check"},
        ],
    })

    context["kpi_groups"] = groups
    return context
