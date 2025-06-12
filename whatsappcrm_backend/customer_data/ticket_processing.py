# whatsappcrm_backend/customer_data/ticket_processing.py

from django.db import transaction
from django.apps import apps
from decimal import Decimal

# Lazy import models to avoid circular dependencies
Contact = apps.get_model('conversations', 'Contact')
CustomerProfile = apps.get_model('customer_data', 'CustomerProfile')
UserWallet = apps.get_model('customer_data', 'UserWallet')
WalletTransaction = apps.get_model('customer_data', 'WalletTransaction')
BetTicket = apps.get_model('customer_data', 'BetTicket')
Bet = apps.get_model('customer_data', 'Bet')
# These models are from football_data_app, so import them via apps.get_model
FootballFixture = apps.get_model('football_data_app', 'FootballFixture') # Corrected: use FootballFixture
MarketOutcome = apps.get_model('football_data_app', 'MarketOutcome')


def process_bet_ticket_submission(
    whatsapp_id: str,
    market_outcome_ids: list[str],
    stake: float,
    bet_type: str = BetTicket.ACCUMULATOR # Default to accumulator
) -> dict:
    """
    Parses the provided market outcome IDs, validates them, creates a bet ticket,
    deducts the stake from the user's wallet, and marks the ticket as placed.

    Args:
        whatsapp_id (str): The WhatsApp ID of the user submitting the ticket.
        market_outcome_ids (list[str]): A list of UUIDs for the MarketOutcome objects.
        stake (float): The total amount staked on the ticket.
        bet_type (str, optional): Type of bet (e.g., 'ACCUMULATOR').

    Returns:
        dict: A dictionary indicating success/failure and relevant messages/data.
    """
    if not market_outcome_ids:
        return {"success": False, "message": "No market outcomes provided for the ticket."}
    if stake <= 0:
        return {"success": False, "message": "Stake must be a positive amount."}

    try:
        with transaction.atomic():
            contact = Contact.objects.get(whatsapp_id=whatsapp_id)
            customer_profile = CustomerProfile.objects.get(contact=contact)
            if not customer_profile.user:
                return {"success": False, "message": "No linked user account found for this contact. Cannot place bet."}

            user_wallet = UserWallet.objects.get(user=customer_profile.user)

            # Check for sufficient funds
            if user_wallet.balance < Decimal(str(stake)):
                return {
                    "success": False,
                    "message": f"Insufficient funds. Your current balance is {float(user_wallet.balance):.2f}.",
                    "new_balance": float(user_wallet.balance)
                }

            # Fetch and validate MarketOutcomes
            valid_outcomes = []
            total_odds = Decimal('1.0')
            for outcome_id in market_outcome_ids:
                try:
                    outcome = MarketOutcome.objects.get(uuid=outcome_id)
                    valid_outcomes.append(outcome)
                    total_odds *= outcome.odds
                except MarketOutcome.DoesNotExist:
                    return {"success": False, "message": f"Invalid market outcome ID found: {outcome_id}"}

            if not valid_outcomes:
                return {"success": False, "message": "No valid market outcomes to place a bet."}

            # Calculate potential winnings
            potential_winnings = Decimal(str(stake)) * total_odds

            # Create BetTicket
            bet_ticket = BetTicket.objects.create(
                user=customer_profile.user,
                total_stake=Decimal(str(stake)),
                potential_winnings=potential_winnings,
                status=BetTicket.PLACED,
                bet_type=bet_type
            )

            # Create individual Bets for the ticket
            for outcome in valid_outcomes:
                Bet.objects.create(
                    ticket=bet_ticket,
                    market_outcome_id=outcome.uuid,
                    odds_at_placement=outcome.odds,
                    stake_per_bet=Decimal(str(stake)) if len(valid_outcomes) == 1 else Decimal(str(stake)) / len(valid_outcomes),
                    status=Bet.PENDING
                )

            # Deduct stake from wallet
            user_wallet.deduct_funds(Decimal(str(stake)), f"Bet placed on ticket {bet_ticket.id}", WalletTransaction.BET_PLACED)

            return {
                "success": True,
                "message": f"Betting ticket (ID: {bet_ticket.id}) successfully placed. Potential winnings: {float(potential_winnings):.2f}. New balance: {float(user_wallet.balance):.2f}.",
                "ticket_id": str(bet_ticket.id),
                "potential_winnings": float(potential_winnings),
                "new_balance": float(user_wallet.balance)
            }

    except Contact.DoesNotExist:
        return {"success": False, "message": "Contact not found."}
    except CustomerProfile.DoesNotExist:
        return {"success": False, "message": "Customer profile not found for this contact."}
    except UserWallet.DoesNotExist:
        return {"success": False, "message": "Wallet not found for the linked user."}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"An unexpected error occurred during ticket processing: {str(e)}"}