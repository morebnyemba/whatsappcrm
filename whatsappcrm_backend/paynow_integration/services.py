# services.py
import logging
from decimal import Decimal
from typing import Optional, Dict, Any

from django.urls import reverse
from django.conf import settings

from .paynow_wrapper import PaynowSDK # Import our wrapper
from .models import PaynowConfig

logger = logging.getLogger(__name__)

class PaynowService:
    """
    Service class to interact with the Paynow API.
    """
    def __init__(self):
        self.config: Optional[PaynowConfig] = None
        self.paynow_sdk: Optional[PaynowSDK] = None
        try:
            self.config = PaynowConfig.objects.first()
            if not self.config:
                logger.error("PaynowConfig not found in database. Please configure Paynow settings.")
            else:
                # Initialize the PaynowSDK with configuration details
                # The SDK constructor requires result_url and return_url
                base_url = getattr(settings, 'SITE_URL', 'https://betblitz.co.zw') # Ensure SITE_URL is configured in settings or .env
                result_url = f"{base_url}{reverse('customer_data_api:paynow-ipn-webhook')}" # IPN callback, defined in customer_data.urls
                return_url = f"{base_url}{reverse('paynow_integration_api:paynow-return')}" # Return URL, defined in paynow_integration.urls

                self.paynow_sdk = PaynowSDK(
                    integration_id=self.config.integration_id,
                    integration_key=self.config.integration_key,
                    result_url=result_url,
                    return_url=return_url
                )
                logger.debug(f"PaynowSDK wrapper successfully initialized for Integration ID: {self.config.integration_id}.")
        except Exception as e: # Catch any exception during initialization
            logger.error(f"Error initializing PaynowService: {type(e).__name__}: {e}", exc_info=True)
            self.paynow_sdk = None # Ensure SDK is None if init fails
    
    def initiate_express_checkout_payment(
        self,
        amount: Decimal, reference: str, phone_number: str, email: str,
        paynow_method_type: str, description: str = "Wallet Deposit"
    ) -> Dict[str, Any]:
        """
        Initiates an Express Checkout payment via Paynow using the SDK.
        """
        if not self.paynow_sdk:
            logger.error("Paynow SDK not initialized when initiate_express_checkout_payment was called. Configuration likely missing or failed to load.")
            return {"success": False, "message": "Paynow service not configured or failed to initialize."}
        
        logger.debug(f"Attempting to initiate Paynow Express Checkout for reference: {reference}, amount: {amount}, phone: {phone_number}, method: {paynow_method_type}.")
        try:
            result = self.paynow_sdk.initiate_express_checkout(
                amount=amount,
                reference=reference,
                phone_number=phone_number,
                email=email,
                paynow_method_type=paynow_method_type,
                description=description
            )
            if result['success']:
                logger.info(f"Paynow Express Checkout initiated successfully for reference: {reference}. PaynowRef: {result.get('paynow_reference')}.")
            else:
                logger.warning(f"Paynow Express Checkout initiation failed for reference: {reference}. Reason: {result.get('message')}.")
            return result
        except Exception as e: # Catch any unexpected exceptions from the SDK call
            logger.error(f"Error during Paynow SDK initiate_express_checkout for reference {reference}: {type(e).__name__}: {e}", exc_info=True)
            return {"success": False, "message": f"Paynow initiation failed: {type(e).__name__} - {e}"}
    
    def check_transaction_status(self, poll_url: str) -> Dict[str, Any]:
        """
        Delegates transaction status check to the PaynowSDK wrapper.
        """
        if not self.paynow_sdk:
            return {"success": False, "message": "Paynow SDK not initialized. Configuration missing."}
        
        logger.debug(f"Attempting to check Paynow transaction status using poll URL: {poll_url}.")
        try:
            result = self.paynow_sdk.check_transaction_status(poll_url)
            if result['success']:
                logger.info(f"Paynow status check successful for {poll_url}. Status: {result.get('status')}, Paid: {result.get('paid')}.")
            else:
                logger.warning(f"Paynow status check failed for {poll_url}. Reason: {result.get('message')}.")
            return result
        except Exception as e:
            logger.error(f"Error during Paynow SDK check_transaction_status for {poll_url}: {type(e).__name__}: {e}", exc_info=True)
            return {"success": False, "message": f"Error checking status: {type(e).__name__} - {e}"}
