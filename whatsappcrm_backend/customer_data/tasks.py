# whatsappcrm_backend/customer_data/tasks.py
import logging
from celery import shared_task
from decimal import Decimal

# Assuming a utility function exists to send messages.
# Import the actual sending utility from meta_integration
from meta_integration.utils import send_whatsapp_message, create_text_message_data

logger = logging.getLogger(__name__)

@shared_task(name="customer_data.send_deposit_confirmation_whatsapp")
def send_deposit_confirmation_whatsapp(whatsapp_id: str, amount: str, new_balance: str, transaction_reference: str, currency_symbol: str = "$"):
    """
    Sends a WhatsApp message to the user confirming their successful deposit.
    We pass arguments as strings because Celery serializers work best with primitive types.
    """
    try:
        # Convert string representations of decimals back to Decimal for formatting
        amount_decimal = Decimal(amount)
        new_balance_decimal = Decimal(new_balance)

        message_body = ( # Renamed to message_body to avoid conflict with send_whatsapp_message parameter
            f"✅ Your deposit has been confirmed!\n\n"
            f"Amount: {currency_symbol}{amount_decimal:.2f}\n"
            f"Reference: {transaction_reference}\n"
            f"New Wallet Balance: {currency_symbol}{new_balance_decimal:.2f}\n\n"
            f"Thank you for topping up!"
        )

        # Create the data payload for a text message
        message_data = create_text_message_data(text_body=message_body, preview_url=False)

        # Call the actual WhatsApp message sending function
        result = send_whatsapp_message(to_phone_number=whatsapp_id, message_type='text', data=message_data)

        if result and result.get("messages"): # Check for Meta API's success indicator
            logger.info(f"Successfully sent deposit confirmation to {whatsapp_id} for transaction {transaction_reference}. Meta message ID: {result['messages'][0]['id']}")
        else:
            logger.error(f"Failed to send WhatsApp deposit confirmation to {whatsapp_id}. Result: {result}")
    except Exception as e:
        logger.error(f"Error in send_deposit_confirmation_whatsapp task for {whatsapp_id}: {e}", exc_info=True)
        # Re-raising the exception can allow Celery to handle retries
        raise