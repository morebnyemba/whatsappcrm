# whatsappcrm_backend/football_data_app/ai_gateway.py
"""
Conversational assistant gateway for BetBlitz (Phase 2).

Design constraints:
- The LLM (Gemini) is used ONLY as an intent matcher, and ONLY as a fallback:
  keyword matching runs first, and Gemini is consulted just to map a free-form
  question to one of a fixed set of intent labels when the keywords don't match.
- The LLM never generates user-facing text. Every answer is templated from real
  database data — no invented odds, results, or balances.
- Bet placement never routes through the assistant; it always goes through the
  confirmable tap flow (betting_flow.py).
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
INTENT_HELP = 'help'

ALL_INTENTS = (INTENT_BALANCE, INTENT_LAST_TICKET, INTENT_OPEN_BETS, INTENT_HELP)

_KEYWORDS = {
    INTENT_BALANCE: ('balance', 'wallet', 'how much', 'funds', 'money'),
    INTENT_LAST_TICKET: ('last ticket', 'last bet', 'my ticket', 'how is my', "how's my", 'did i win', 'result'),
    INTENT_OPEN_BETS: ('open bet', 'open ticket', 'pending', 'my bets', 'active bet'),
    INTENT_HELP: ('help', 'how do', 'what can you'),
}


def _keyword_intent(text: str) -> str | None:
    """Keyword-based intent match. Returns None when nothing matches."""
    t = (text or '').lower()
    for intent in (INTENT_BALANCE, INTENT_LAST_TICKET, INTENT_OPEN_BETS):
        if any(k in t for k in _KEYWORDS[intent]):
            return intent
    if any(k in t for k in _KEYWORDS[INTENT_HELP]):
        return INTENT_HELP
    return None


class GeminiGateway:
    """Thin Gemini wrapper used solely for fallback intent classification."""

    def __init__(self):
        self.api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
        self.model = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def match_intent(self, text: str, timeout: int = 10) -> str | None:
        """
        Map free text to one of ALL_INTENTS using the LLM. Returns a valid intent
        label or None. The model is constrained to output only a label; anything
        outside ALL_INTENTS is rejected so the LLM can never inject free-form text.
        """
        if not self.enabled:
            return None
        try:
            import requests
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{self.model}:generateContent?key={self.api_key}")
            system = (
                "You are an intent classifier for a sports-betting assistant. "
                "Respond with EXACTLY ONE of these labels and nothing else: "
                + ", ".join(ALL_INTENTS) + "."
            )
            prompt = f"{system}\n\nUser message: {text!r}\nLabel:"
            resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=timeout)
            resp.raise_for_status()
            label = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip().lower()
            # Only accept a recognised label; never surface raw model text.
            for intent in ALL_INTENTS:
                if intent in label:
                    return intent
            return None
        except Exception as e:
            logger.warning(f"Gemini intent match failed, using keyword result: {e}")
            return None


def classify_intent(text: str) -> str:
    """
    Keyword matching first; Gemini only as a fallback intent matcher when the
    keywords don't resolve. Defaults to HELP.
    """
    intent = _keyword_intent(text)
    if intent is not None:
        return intent
    llm_intent = GeminiGateway().match_intent(text)
    return llm_intent or INTENT_HELP


def _user_from_contact(contact):
    profile = getattr(contact, 'customerprofile', None)
    return getattr(profile, 'user', None) if profile else None


def answer_question(contact, text: str) -> str:
    """Answer a free-form question from DB data (templated; never LLM-generated)."""
    from customer_data.models import UserWallet, BetTicket

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

    # INTENT_HELP / default
    return ("I'm your BetBlitz assistant 🤖. Ask me things like *what's my balance*, "
            "*how's my last ticket*, or *any open bets*. To place a bet, reply *bet*. "
            "Please gamble responsibly.")
