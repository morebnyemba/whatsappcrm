# views.py
import logging
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import PaynowConfig
from .paynow_wrapper import PaynowSDK # Import the SDK wrapper
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
