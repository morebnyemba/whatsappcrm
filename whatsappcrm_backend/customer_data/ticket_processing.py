# whatsappcrm_backend/customer_data/ticket_processing.py

from django.db import transaction
from django.apps import apps
from decimal import Decimal
import logging

# Initialize logger
logger = logging.getLogger(__name__)

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
    # Validation constants
    MIN_STAKE = 0.50  # Minimum stake of 50 cents
    MAX_STAKE = 10000.00  # Maximum stake of $10,000
    MAX_SELECTIONS = 20  # Maximum number of selections per ticket
    
    # Input validation
    if not market_outcome_ids:
        return {"success": False, "message": "No market outcomes provided for the ticket."}
    
    if len(market_outcome_ids) > MAX_SELECTIONS:
        return {"success": False, "message": f"Maximum {MAX_SELECTIONS} selections allowed per ticket. You have {len(market_outcome_ids)} selections."}
    
    if stake <= 0:
        return {"success": False, "message": "Stake must be a positive amount."}
    
    if stake < MIN_STAKE:
        return {"success": False, "message": f"Minimum stake is ${MIN_STAKE:.2f}. Your stake is ${stake:.2f}."}
    
    if stake > MAX_STAKE:
        return {"success": False, "message": f"Maximum stake is ${MAX_STAKE:.2f}. Your stake is ${stake:.2f}."}

    logger.info(f"Processing bet ticket submission for WhatsApp ID: {whatsapp_id}, Stake: ${stake:.2f}, Selections: {len(market_outcome_ids)}")
    
    try:
        with transaction.atomic():
            contact = Contact.objects.get(whatsapp_id=whatsapp_id)
            customer_profile = CustomerProfile.objects.get(contact=contact)
            if not customer_profile.user:
                logger.warning(f"No linked user account for WhatsApp ID: {whatsapp_id}")
                return {"success": False, "message": "No linked user account found for this contact. Cannot place bet."}

            # Lock the wallet row for the duration of the transaction to prevent race conditions.
            # This ensures the balance check and deduction are atomic.
            user_wallet = UserWallet.objects.select_for_update().get(user=customer_profile.user)

            # Check for sufficient funds
            if user_wallet.balance < Decimal(str(stake)):
                return {
                    "success": False,
                    "message": f"Insufficient funds. Your current balance is {float(user_wallet.balance):.2f}.",
                    "new_balance": float(user_wallet.balance)
                }

            # Fetch and validate MarketOutcomes
            int_market_outcome_ids = [int(i) for i in market_outcome_ids]
            valid_outcomes = list(MarketOutcome.objects.filter(
                id__in=int_market_outcome_ids,
                is_active=True
            ).select_related(
                'market__fixture__home_team',
                'market__fixture__away_team',
                'market__category',
                'market__fixture'
            ))

            if len(valid_outcomes) != len(int_market_outcome_ids):
                found_ids = {str(o.id) for o in valid_outcomes}
                missing_ids = [i for i in market_outcome_ids if i not in found_ids]
                return {"success": False, "message": f"Invalid or unavailable market outcome IDs found: {', '.join(missing_ids)}"}

            if not valid_outcomes:
                return {"success": False, "message": "No valid market outcomes to place a bet."}

            # Check that all fixtures are in a bettable state (not finished, cancelled, or postponed)
            for outcome in valid_outcomes:
                fixture = outcome.market.fixture
                if fixture.status in [FootballFixture.FixtureStatus.FINISHED, 
                                     FootballFixture.FixtureStatus.CANCELLED, 
                                     FootballFixture.FixtureStatus.POSTPONED]:
                    return {
                        "success": False, 
                        "message": f"Cannot bet on match '{fixture.home_team.name} vs {fixture.away_team.name}' - match status is {fixture.status}."
                    }
            
            # Calculate total odds
            total_odds = Decimal('1.0')
            for outcome in valid_outcomes:
                if outcome.odds <= Decimal('1.0'):
                    return {
                        "success": False,
                        "message": f"Invalid odds ({outcome.odds}) for selection '{outcome.outcome_name}'. Odds must be greater than 1.0."
                    }
                total_odds *= outcome.odds

            # Determine bet type
            bet_type = 'SINGLE' if len(valid_outcomes) == 1 else 'MULTIPLE'

            # Calculate potential winnings
            potential_winnings = Decimal(str(stake)) * total_odds

            # Create BetTicket
            bet_ticket = BetTicket.objects.create(
                user=customer_profile.user,
                total_stake=Decimal(str(stake)),
                potential_winnings=potential_winnings,
                status='PENDING',
                bet_type=bet_type
            )

            # Create individual Bets for the ticket
            for outcome in valid_outcomes:
                # For both SINGLE and MULTIPLE, the amount on the bet leg can be considered the full stake.
                # The potential winnings of the leg is based on its own odds. The ticket's potential
                # winnings will be based on the combined odds.
                bet_amount = Decimal(str(stake))
                potential_winnings_for_bet = bet_amount * outcome.odds

                Bet.objects.create(
                    ticket=bet_ticket,
                    market_outcome=outcome,
                    amount=bet_amount, # Use the full stake
                    potential_winnings=potential_winnings_for_bet, # Provide the value here
                    status='PENDING'
                )

            # Now, place the ticket (this will update its status to PLACED)
            logger.info(f"Placing ticket #{bet_ticket.id} for user {customer_profile.user.username}")
            bet_ticket.place_ticket()

            # Refresh the wallet object from the database to get the updated balance
            # after the deduction made inside place_ticket().
            user_wallet.refresh_from_db()
            
            logger.info(f"Ticket #{bet_ticket.id} placed successfully. New wallet balance: ${user_wallet.balance:.2f}")

            # Build the detailed success message, not truncated
            success_message = f"✅ Ticket #{bet_ticket.id} placed successfully!\n\n"
            success_message += f"Stake: ${float(bet_ticket.total_stake):.2f}\n"
            success_message += f"Potential Winnings: ${float(bet_ticket.potential_winnings):.2f}\n"
            success_message += "-------------------\n\n"
            success_message += "*Your Selections:*\n"

            # The `valid_outcomes` list already has the prefetched data
            for outcome in valid_outcomes:
                fixture = outcome.market.fixture
                fixture_name = f"{fixture.home_team.name} vs {fixture.away_team.name}"
                success_message += f"  - Match: {fixture_name}\n"
                success_message += f"    Selection: {outcome.outcome_name} ({outcome.market.category.name})\n"
                success_message += f"    Odds: {float(outcome.odds):.2f}\n\n"

            success_message += f"Your new balance is: ${float(user_wallet.balance):.2f}"

            return {
                "success": True,
                "message": success_message,
                "ticket_id": str(bet_ticket.id),
                "potential_winnings": float(potential_winnings),
                "new_balance": float(user_wallet.balance)
            }

    except Contact.DoesNotExist:
        logger.error(f"Contact not found for WhatsApp ID: {whatsapp_id}")
        return {"success": False, "message": "Contact not found."}
    except CustomerProfile.DoesNotExist:
        logger.error(f"Customer profile not found for WhatsApp ID: {whatsapp_id}")
        return {"success": False, "message": "Customer profile not found for this contact."}
    except UserWallet.DoesNotExist:
        logger.error(f"Wallet not found for WhatsApp ID: {whatsapp_id}")
        return {"success": False, "message": "Wallet not found for the linked user."}
    except ValueError as e:
        logger.warning(f"Validation error during bet ticket submission: {str(e)}")
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.exception(f"Unexpected error during ticket processing for WhatsApp ID {whatsapp_id}: {str(e)}")
        return {"success": False, "message": f"An unexpected error occurred during ticket processing: {str(e)}"}