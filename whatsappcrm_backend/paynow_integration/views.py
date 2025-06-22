# views.py
import logging
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import PaynowConfig
from .paynow_wrapper import PaynowSDK # Import the SDK wrapper
from .services import PaynowService # Import PaynowService to get config
from customer_data.utils import record_deposit_transaction # Import the recording function
from conversations.models import Contact # Assuming you need to find the contact by whatsapp_id

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["POST", "GET"])
def paynow_return_view(request: HttpRequest) -> HttpResponse:
    """
    Handles the return URL from Paynow after a user completes (or cancels) a payment.
    This is usually a browser redirect.
    """
    status = request.GET.get('status', 'unknown')
    reference = request.GET.get('reference')
    paynow_reference = request.GET.get('paynowreference')
    
    logger.info(f"Paynow Return URL hit. Status: {status}, Reference: {reference}, PaynowRef: {paynow_reference}")
    
    # You might want to redirect the user to a specific page in your app
    # based on the status (e.g., success page, pending page, failed page).
    # For now, a simple message.
    if status == 'Paid':
        # Payment was successful, but the IPN (resulturl) is the definitive source.
        # Here, you might show a "Payment successful, awaiting confirmation" message.
        return HttpResponse(f"Payment for {reference} was successful. Thank you! We are confirming your transaction.")
    elif status == 'Cancelled':
        return HttpResponse(f"Payment for {reference} was cancelled. Please try again.")
    else:
        return HttpResponse(f"Payment status for {reference}: {status}. Please check your transaction history.")

@csrf_exempt
@require_http_methods(["POST"])
def paynow_result_view(request: HttpRequest) -> HttpResponse:
    """
    Handles the result URL (IPN - Instant Payment Notification) from Paynow.
    This is a server-to-server callback that confirms the payment status.
    """
    logger.info("Paynow Result URL (IPN) hit.")
    
    # Paynow sends data as form-encoded.
    data = request.POST.dict()
    logger.debug(f"Paynow IPN data: {data}")

    status = data.get('status')
    reference = data.get('reference') # Our internal transaction reference
    paynow_reference = data.get('paynowreference')
    amount = data.get('amount')
    hash_received = data.get('hash')
    
    # Use PaynowService to get the config and then initialize SDK for verification
    paynow_service = PaynowService()
    if not paynow_service.config:
        logger.error("PaynowConfig not found for IPN verification in PaynowService.")
        return HttpResponse("Configuration Error", status=500) # Or a more specific error
    
    # Initialize the SDK wrapper for IPN verification.
    # The result_url and return_url are not used for IPN hash verification,
    # but are required by the SDK's constructor.
    sdk = PaynowSDK(
        integration_id=paynow_service.config.integration_id,
        integration_key=paynow_service.config.integration_key,
        result_url="", return_url="" # Placeholder values as they are not used for IPN verification
    )
    
    if not sdk.verify_ipn_callback(data):
        logger.warning(f"Paynow IPN hash mismatch for reference {reference}. Received: {hash_received}, Expected: {sdk.verify_ipn_callback(data)}") # Log actual expected hash for debugging
        return HttpResponse("Hash Mismatch", status=400)

    if status == 'Paid':
        # Extract whatsapp_id from our internal reference (e.g., "DEP-123-TIMESTAMP")
        try:
            # Assuming reference format "DEP-{profile.id}-{timestamp}"
            # This needs to be robust. A better way is to store the reference in a PendingTransaction model
            # and link it to the Contact/CustomerProfile. For now, we'll try to parse.
            parts = reference.split('-')
            if len(parts) >= 2 and parts[0] == 'DEP':
                profile_id = int(parts[1])
                contact = Contact.objects.filter(customerprofile__id=profile_id).first()
            else:
                # Fallback if reference format is not as expected, try to find contact by email or other means
                # For now, log and return error if parsing fails
                logger.error(f"Paynow IPN reference format not recognized: {reference}. Cannot extract profile ID.")
                return HttpResponse("Invalid Reference Format", status=400)

            if contact:
                # Record the deposit
                record_deposit_transaction(
                    whatsapp_id=contact.whatsapp_id,
                    amount=float(amount),
                    description=f"Paynow Mobile Deposit (Ref: {paynow_reference})",
                    transaction_id=paynow_reference,
                    payment_method='paynow_mobile'
                )
                logger.info(f"Successfully recorded Paynow deposit for {contact.whatsapp_id}, Ref: {reference}")
                return HttpResponse("OK", status=200)
            else:
                logger.error(f"Contact not found for profile ID {profile_id} from Paynow IPN reference {reference}.")
                return HttpResponse("Contact Not Found", status=404)
        except Exception as e:
            logger.error(f"Error processing Paynow IPN for reference {reference}: {e}", exc_info=True)
            return HttpResponse("Internal Server Error", status=500)
    elif status == 'Cancelled' or status == 'Failed':
        logger.info(f"Paynow IPN: Transaction {reference} {status}.")
        # You might want to log this or update a pending transaction status
        return HttpResponse("OK", status=200)
    else:
        logger.warning(f"Paynow IPN: Unhandled status '{status}' for reference {reference}.")
        return HttpResponse("OK", status=200) # Always return OK to Paynow to avoid retries
