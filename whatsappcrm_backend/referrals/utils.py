# whatsappcrm_backend/referrals/utils.py

import logging
from django.db import transaction
from decimal import Decimal
from django.contrib.auth import get_user_model
from .models import ReferralProfile, ReferralSettings, AgentEarning, AgentDeduction, AgentDepositBonus, AgentApplication
from customer_data.models import UserWallet, WalletTransaction, CustomerProfile
from .tasks import send_bonus_notification_task

logger = logging.getLogger(__name__)
User = get_user_model()

def get_or_create_referral_profile(user: User) -> ReferralProfile:
    """
    Retrieves or creates a ReferralProfile for a given user.
    The referral code is generated automatically on creation by the model's default.
    """
    profile, created = ReferralProfile.objects.get_or_create(user=user)
    if created:
        logger.info(f"Created ReferralProfile for user {user.username} with code {profile.referral_code}")
    return profile

def link_referral(new_user: User, referral_code: str):
    """
    Links a new user to a referrer if the code is valid.
    This should be called during account creation.
    """
    if not referral_code:
        return

    try:
        referrer_profile = ReferralProfile.objects.select_related('user').get(referral_code__iexact=referral_code)
        new_user_profile = get_or_create_referral_profile(new_user)
        
        # Prevent self-referral
        if new_user_profile.user == referrer_profile.user:
            logger.warning(f"User {new_user.username} attempted self-referral with code {referral_code}.")
            return

        new_user_profile.referred_by = referrer_profile.user
        new_user_profile.save(update_fields=['referred_by'])
        logger.info(f"User {new_user.username} was successfully referred by {referrer_profile.user.username}")
    except ReferralProfile.DoesNotExist:
        logger.warning(f"Invalid referral code '{referral_code}' used by user {new_user.username}.")

def apply_to_be_agent(user: User) -> dict:
    """
    Records a user's self-service request to become an agent. is_agent
    itself stays admin-only (see AgentApplicationAdmin.approve_applications)
    -- this just gives the user a real path forward instead of the old
    dead-end "contact support" message, and gives an admin a queue to work
    from instead of needing shell/DB access to enroll anyone.
    """
    profile = get_or_create_referral_profile(user)
    if profile.is_agent:
        return {"success": False, "message": "You're already an agent! Type 'agent' to see your options."}

    existing = AgentApplication.objects.filter(user=user, status=AgentApplication.Status.PENDING).first()
    if existing:
        return {"success": False, "message": "You already have an application pending review. We'll notify you once it's been reviewed."}

    AgentApplication.objects.create(user=user)
    logger.info(f"User {user.username} applied to become an agent.")
    return {"success": True, "message": "Thanks! Your agent application has been submitted for review. We'll notify you once it's been reviewed."}

def get_referrer_details_from_code(referral_code: str) -> dict:
    """
    Finds a referrer by their code and returns their details for confirmation.
    """
    if not referral_code:
        return {"success": False, "message": "No code provided."}

    try:
        # Find the profile with the given code
        referrer_profile = ReferralProfile.objects.select_related('user__customer_profile').get(referral_code__iexact=referral_code)
        
        # Get the referrer's user and customer profile
        referrer_user = referrer_profile.user
        referrer_customer_profile = referrer_user.customer_profile
        
        # Construct the name to display, preferring first_name
        referrer_name = referrer_customer_profile.first_name or referrer_user.username
        
        return {
            "success": True,
            "referrer_name": referrer_name,
            "referral_code": referrer_profile.referral_code, # Also return the code itself
            "message": f"Referrer found: {referrer_name}"
        }
    except (ReferralProfile.DoesNotExist, CustomerProfile.DoesNotExist):
        return {"success": False, "message": "Invalid referral code."}
    except Exception as e:
        logger.error(f"Error getting referrer details for code {referral_code}: {e}", exc_info=True)
        return {"success": False, "message": "An unexpected error occurred."}

def apply_referral_bonus(new_user: User, deposit_transaction: WalletTransaction):
    """
    Applies a percentage-based referral bonus to the new (referred) user based
    on the amount of their first deposit. If the referrer is an admin-designated
    agent, the agent also receives the same percentage bonus on that same
    qualifying deposit (recorded as an AgentDepositBonus). Referrers who are
    not designated agents don't earn this side of the bonus — matches how
    agent loss-commission is already gated (see award_agent_commission).
    This is an internal function called by check_and_apply_first_deposit_bonus.
    """
    profile = get_or_create_referral_profile(new_user)
    if not profile.referred_by or profile.referral_bonus_applied:
        return {"success": False, "message": "No referrer or bonus already applied."}

    first_deposit_amount = deposit_transaction.amount
    if first_deposit_amount <= 0:
        return {"success": False, "message": "First deposit amount is zero or less."}

    # Calculate the bonus amount for the new user from the settings
    settings = ReferralSettings.load()
    bonus_amount = first_deposit_amount * settings.bonus_percentage_each

    referrer_user = profile.referred_by
    referrer_profile = ReferralProfile.objects.filter(user=referrer_user).first()
    is_agent = bool(referrer_profile and referrer_profile.is_agent)

    with transaction.atomic():
        # Credit the new (referred) user.
        new_user.wallet.add_funds(bonus_amount, description=f"Referral bonus from {referrer_user.username}", transaction_type='BONUS')

        agent_bonus_amount = Decimal('0.00')
        if is_agent:
            agent_bonus_amount = bonus_amount
            referrer_user.wallet.add_funds(
                agent_bonus_amount,
                description=f"Agent deposit bonus from {new_user.username}'s first deposit",
                transaction_type='AGENT_DEPOSIT_BONUS',
            )
            AgentDepositBonus.objects.create(
                agent_profile=referrer_profile,
                referred_user=new_user,
                deposit_transaction=deposit_transaction,
                deposit_amount=first_deposit_amount,
                bonus_percentage=settings.bonus_percentage_each,
                bonus_amount=agent_bonus_amount,
            )

        profile.referral_bonus_applied = True
        profile.save(update_fields=['referral_bonus_applied'])

    logger.info(f"Applied referral bonus of ${bonus_amount:.2f} to {new_user.username} based on a deposit of ${first_deposit_amount:.2f}")

    bonus_percentage_display = f"{settings.bonus_percentage_each:.2%}"
    # Notify the new user
    new_user_message = f"🎉 Congratulations! You've received a ${bonus_amount:.2f} ({bonus_percentage_display}) referral bonus on your first deposit!"
    send_bonus_notification_task.delay(user_id=new_user.id, message=new_user_message)

    if is_agent:
        logger.info(f"Applied agent deposit bonus of ${agent_bonus_amount:.2f} to {referrer_user.username} from {new_user.username}'s first deposit.")
        agent_message = (
            f"💰 Agent Deposit Bonus Earned!\n\n"
            f"Your referral {new_user.username} made their first deposit of ${first_deposit_amount:.2f}.\n\n"
            f"You've earned a *${agent_bonus_amount:.2f}* ({bonus_percentage_display}) bonus! "
            f"Your wallet has been credited."
        )
        send_bonus_notification_task.delay(user_id=referrer_user.id, message=agent_message)

    return {"success": True, "message": f"Successfully applied a ${bonus_amount:.2f} bonus to your account!"}

def check_and_apply_first_deposit_bonus(user: User):
    """
    Checks if a user is eligible for a first-deposit referral bonus and applies it.
    This should be called after any successful deposit transaction is completed.
    """
    try:
        profile = get_or_create_referral_profile(user)

        # Condition 1: User must have been referred by someone.
        if not profile.referred_by:
            return

        # Condition 2: The bonus must not have been applied already.
        if profile.referral_bonus_applied:
            return

        # Condition 3: This must be the user's *first* completed deposit.
        # We check if there is exactly one completed deposit transaction for this user's wallet.
        completed_deposits_count = WalletTransaction.objects.filter(
            wallet__user=user,
            transaction_type='DEPOSIT',
            status='COMPLETED'
        ).count()

        if completed_deposits_count == 1:
            # Fetch the actual deposit transaction to get its amount
            first_deposit_transaction = WalletTransaction.objects.get(
                wallet__user=user,
                transaction_type='DEPOSIT',
                status='COMPLETED'
            )
            logger.info(f"User {user.username} has made their first deposit. Applying referral bonus.")
            apply_referral_bonus(user, first_deposit_transaction)

    except Exception as e:
        logger.error(f"Error in check_and_apply_first_deposit_bonus for user {user.username}: {e}", exc_info=True)


def award_agent_commission(ticket):
    """
    Awards a commission to the agent who referred the user that lost a bet.
    Called during bet ticket settlement when a ticket status is LOST.

    Args:
        ticket: The BetTicket instance that was lost.
    """
    log_prefix = f"[Agent Commission - Ticket #{ticket.id}]"

    if not ticket.user:
        logger.debug(f"{log_prefix} No user on ticket. Skipping agent commission.")
        return

    try:
        # Check if the losing bettor was referred by an agent
        profile = ReferralProfile.objects.select_related('referred_by').get(user=ticket.user)
    except ReferralProfile.DoesNotExist:
        logger.debug(f"{log_prefix} No referral profile for user {ticket.user.username}. Skipping.")
        return

    if not profile.referred_by:
        logger.debug(f"{log_prefix} User {ticket.user.username} has no agent. Skipping.")
        return

    agent_user = profile.referred_by

    # Only award commission to admin-designated agents
    try:
        agent_profile = ReferralProfile.objects.get(user=agent_user)
    except ReferralProfile.DoesNotExist:
        logger.debug(f"{log_prefix} Agent {agent_user.username} has no referral profile. Skipping.")
        return

    # Prevent duplicate commission for the same ticket (early exit before is_agent check)
    if AgentEarning.objects.filter(agent_profile=agent_profile, bet_ticket=ticket).exists():
        logger.info(f"{log_prefix} Commission already awarded to agent {agent_user.username}. Skipping.")
        return

    if not agent_profile.is_agent:
        logger.debug(f"{log_prefix} User {agent_user.username} is not a designated agent. Skipping commission.")
        return

    settings = ReferralSettings.load()
    commission_pct = settings.agent_commission_percentage

    if commission_pct <= 0:
        logger.debug(f"{log_prefix} Agent commission percentage is 0. Skipping.")
        return

    commission_amount = Decimal(str(ticket.total_stake)) * Decimal(str(commission_pct))

    if commission_amount <= 0:
        logger.debug(f"{log_prefix} Commission amount is zero or negative. Skipping.")
        return

    with transaction.atomic():
        # Record the earning
        AgentEarning.objects.create(
            agent_profile=agent_profile,
            bet_ticket=ticket,
            referred_user=ticket.user,
            bet_stake=ticket.total_stake,
            commission_percentage=commission_pct,
            commission_amount=commission_amount,
        )

        # Credit agent's wallet
        agent_user.wallet.add_funds(
            amount=commission_amount,
            description=f"Agent commission from {ticket.user.username}'s lost ticket #{ticket.id}",
            transaction_type='AGENT_COMMISSION',
        )

    logger.info(
        f"{log_prefix} Awarded ${commission_amount:.2f} ({commission_pct:.2%}) commission "
        f"to agent {agent_user.username} from {ticket.user.username}'s lost stake of ${ticket.total_stake:.2f}."
    )

    # Send notification to agent
    commission_message = (
        f"💰 Agent Commission Earned!\n\n"
        f"Your referred user {ticket.user.username} lost a bet (Ticket #{ticket.id}) "
        f"with a stake of ${ticket.total_stake:.2f}.\n\n"
        f"You've earned a *${commission_amount:.2f}* ({commission_pct:.2%}) commission! "
        f"Your wallet has been credited."
    )
    send_bonus_notification_task.delay(user_id=agent_user.id, message=commission_message)


def apply_agent_win_deduction(ticket, winnings):
    """
    Deducts a percentage of a referred user's winnings from the referring
    agent's wallet. Called during bet ticket settlement when a ticket status
    is WON — the mirror image of award_agent_commission() (which credits the
    agent on a referred user's loss).

    The deduction is unconditional (per the affiliate program's rules) and
    may take the agent's wallet negative — it does not block or reduce the
    referred user's own payout, which has already been credited by the time
    this runs.

    Args:
        ticket: The BetTicket instance that was won.
        winnings: The Decimal amount the referred user won on this ticket.
    """
    log_prefix = f"[Agent Win Deduction - Ticket #{ticket.id}]"

    if not ticket.user:
        logger.debug(f"{log_prefix} No user on ticket. Skipping agent deduction.")
        return

    try:
        profile = ReferralProfile.objects.select_related('referred_by').get(user=ticket.user)
    except ReferralProfile.DoesNotExist:
        logger.debug(f"{log_prefix} No referral profile for user {ticket.user.username}. Skipping.")
        return

    if not profile.referred_by:
        logger.debug(f"{log_prefix} User {ticket.user.username} has no agent. Skipping.")
        return

    agent_user = profile.referred_by

    try:
        agent_profile = ReferralProfile.objects.get(user=agent_user)
    except ReferralProfile.DoesNotExist:
        logger.debug(f"{log_prefix} Agent {agent_user.username} has no referral profile. Skipping.")
        return

    # Prevent duplicate deduction for the same ticket (early exit before is_agent check)
    if AgentDeduction.objects.filter(agent_profile=agent_profile, bet_ticket=ticket).exists():
        logger.info(f"{log_prefix} Deduction already applied to agent {agent_user.username}. Skipping.")
        return

    if not agent_profile.is_agent:
        logger.debug(f"{log_prefix} User {agent_user.username} is not a designated agent. Skipping deduction.")
        return

    settings = ReferralSettings.load()
    deduction_pct = settings.agent_win_deduction_percentage

    if deduction_pct <= 0:
        logger.debug(f"{log_prefix} Agent win deduction percentage is 0. Skipping.")
        return

    winnings = Decimal(str(winnings))
    deduction_amount = winnings * Decimal(str(deduction_pct))

    if deduction_amount <= 0:
        logger.debug(f"{log_prefix} Deduction amount is zero or negative. Skipping.")
        return

    with transaction.atomic():
        # Record the deduction
        AgentDeduction.objects.create(
            agent_profile=agent_profile,
            bet_ticket=ticket,
            referred_user=ticket.user,
            win_amount=winnings,
            deduction_percentage=deduction_pct,
            deduction_amount=deduction_amount,
        )

        # Deduct from the agent's wallet — unconditional; may go negative.
        agent_user.wallet.deduct_funds_allow_negative(
            amount=deduction_amount,
            description=f"Agent win deduction from {ticket.user.username}'s won ticket #{ticket.id}",
            transaction_type='AGENT_WIN_DEDUCTION',
        )

    logger.info(
        f"{log_prefix} Deducted ${deduction_amount:.2f} ({deduction_pct:.2%}) from agent "
        f"{agent_user.username} for {ticket.user.username}'s win of ${winnings:.2f}."
    )

    # Send notification to agent
    deduction_message = (
        f"⚠️ Agent Win Deduction\n\n"
        f"Your referred user {ticket.user.username} won a bet (Ticket #{ticket.id}) "
        f"with winnings of ${winnings:.2f}.\n\n"
        f"*${deduction_amount:.2f}* ({deduction_pct:.2%}) has been deducted from your wallet."
    )
    send_bonus_notification_task.delay(user_id=agent_user.id, message=deduction_message)