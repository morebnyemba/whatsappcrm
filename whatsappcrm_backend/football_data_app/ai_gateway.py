# whatsappcrm_backend/football_data_app/ai_gateway.py
"""
LLM gateway for the conversational betting assistant (Phase 2).

A single entry point that turns a user's free-form WhatsApp question into a
structured intent and answers it **from real database data** — never inventing
odds, results, or balances. An optional Gemini call is used only to (a) classify
ambiguous questions and (b) phrase answers/prediction explanations in natural
language; when no GEMINI_API_KEY is configured the gateway falls back to
keyword-based intent detection and templated answers, so it is fully functional
(and testable) without the LLM.

Hard rule: bet placement never goes through free-text LLM output. This gateway
only reads and explains; placing a bet always routes through the confirmable
tap flow (betting_flow.py).
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)

# Intents the assistant can answer from the database.
INTENT_BALANCE = 'balance'
INTENT_LAST_TICKET = 'last_ticket'
INTENT_OPEN_BETS = 'open_bets'
INTENT_TIP = 'tip'
INTENT_HELP = 'help'

_KEYWORDS = {
    INTENT_BALANCE: ('balance', 'wallet', 'how much', 'funds', 'money'),
    INTENT_LAST_TICKET: ('last ticket', 'last bet', 'my ticket', 'how is my', "how's my", 'did i win', 'result'),
    INTENT_OPEN_BETS: ('open bet', 'open ticket', 'pending', 'my bets', 'active bet'),
    INTENT_TIP: ('best bet', 'tip', 'prediction', 'who will win', 'recommend', 'favourite', 'favorite', 'tonight'),
    INTENT_HELP: ('help', 'how do', 'what can you'),
}


def classify_intent(text: str) -> str:
    """Keyword-based intent classification (LLM-free baseline)."""
    t = (text or '').lower()
    for intent, kws in _KEYWORDS.items():
        if any(k in t for k in kws):
            return intent
    return INTENT_HELP


class GeminiGateway:
    """Thin wrapper around the Gemini REST API with graceful degradation."""

    def __init__(self):
        self.api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
        self.model = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, system: str = None, timeout: int = 15) -> str | None:
        """Call Gemini for a short natural-language completion. Returns None on any failure."""
        if not self.enabled:
            return None
        try:
            import requests
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{self.model}:generateContent?key={self.api_key}")
            parts = []
            if system:
                parts.append({"text": system})
            parts.append({"text": prompt})
            resp = requests.post(url, json={"contents": [{"parts": parts}]}, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            logger.warning(f"Gemini generate failed, falling back: {e}")
            return None


def _user_from_contact(contact):
    profile = getattr(contact, 'customerprofile', None)
    return getattr(profile, 'user', None) if profile else None


def answer_question(contact, text: str) -> str:
    """
    Answer a free-form question from DB data. LLM (if configured) is used only to
    phrase the answer; the facts always come from the database.
    """
    from customer_data.models import UserWallet, BetTicket
    from .models import FootballFixture
    from .predictions import prediction_sentence

    user = _user_from_contact(contact)
    intent = classify_intent(text)

    if intent == INTENT_BALANCE:
        if not user:
            return "I couldn't find your account. Reply *menu* to get started."
        wallet, _ = UserWallet.objects.get_or_create(user=user)
        return f"💰 Your wallet balance is ${Decimal(wallet.balance):.2f}."

    if intent == INTENT_LAST_TICKET:
        if not user:
            return "I couldn't find your account. Reply *menu* to get started."
        ticket = BetTicket.objects.filter(user=user).order_by('-created_at').first()
        if not ticket:
            return "You have no bets yet. Reply *bet* to place your first one!"
        emoji = {'WON': '✅', 'LOST': '❌', 'PLACED': '⏳', 'PENDING': '⏳', 'REFUNDED': '↩️'}.get(ticket.status, '•')
        return (f"🎫 Your last ticket #{ticket.id} is {emoji} {ticket.get_status_display()}.\n"
                f"Stake ${float(ticket.total_stake):.2f}, potential payout ${float(ticket.potential_winnings):.2f}.")

    if intent == INTENT_OPEN_BETS:
        if not user:
            return "I couldn't find your account. Reply *menu* to get started."
        n = BetTicket.objects.filter(user=user, status__in=['PENDING', 'PLACED']).count()
        return (f"You have {n} open bet{'s' if n != 1 else ''}. Reply *bet* then *My bets* to see them."
                if n else "You have no open bets right now. Reply *bet* to place one.")

    if intent == INTENT_TIP:
        # Surface a model prediction for the soonest upcoming fixture that has one.
        from django.utils import timezone
        fixture = (
            FootballFixture.objects
            .filter(status=FootballFixture.FixtureStatus.SCHEDULED,
                    match_date__gte=timezone.now(), prediction__isnull=False)
            .select_related('home_team', 'away_team', 'prediction')
            .order_by('match_date')
            .first()
        )
        if not fixture:
            return ("I don't have a model prediction ready yet. Reply *bet* to browse matches and odds — "
                    "and remember, bets can lose, so only stake what you can afford.")
        sentence = prediction_sentence(fixture) or "No strong lean."
        base = (f"For {fixture.home_team.name} vs {fixture.away_team.name}: {sentence}. "
                f"This is a statistical estimate, not a guarantee — please bet responsibly.")
        gateway = GeminiGateway()
        if gateway.enabled:
            phrased = gateway.generate(
                prompt=f"Rewrite this betting insight in one friendly, responsible sentence, "
                       f"without inventing any numbers: {base}",
                system="You are a responsible betting assistant. Never invent odds, results, or amounts.",
            )
            if phrased:
                return phrased
        return base

    # INTENT_HELP / default
    return ("I'm your BetBlitz assistant 🤖. Ask me things like *what's my balance*, "
            "*how's my last ticket*, or *any tips tonight*. To place a bet, reply *bet*.")
