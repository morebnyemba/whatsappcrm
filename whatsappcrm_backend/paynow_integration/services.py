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
                base_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')
                result_url = f"{base_url}{reverse('paynow_result')}" # IPN callback
                return_url = f"{base_url}{reverse('paynow_return')}"

                self.paynow_sdk = PaynowSDK(
                    integration_id=self.config.integration_id,
                    integration_key=self.config.integration_key,
                    result_url=result_url,
                    return_url=return_url
                )
        except Exception as e:
            logger.error(f"Error loading PaynowConfig: {e}")
    
    def initiate_express_checkout_payment(
        self,
        amount: Decimal,
        reference: str,
        phone_number: str,
        email: str,
        paynow_method_type: str,
        description: str = "Wallet Deposit"
    ) -> Dict[str, Any]:
        """
        Initiates an Express Checkout payment via Paynow using the SDK.
        """
        if not self.paynow_sdk:
            return {"success": False, "message": "Paynow SDK not initialized. Configuration missing."}
    
        # The SDK wrapper's constructor already has the result_url and return_url
        # from the PaynowService's __init__.
        return self.paynow_sdk.initiate_express_checkout(
            amount=amount,
            reference=reference,
            phone_number=phone_number,
            email=email,
            paynow_method_type=paynow_method_type,
            description=description
        )
    
    def check_transaction_status(self, poll_url: str) -> Dict[str, Any]:
        """
        Delegates transaction status check to the PaynowSDK wrapper.
        """
        if not self.paynow_sdk:
            return {"success": False, "message": "Paynow SDK not initialized. Configuration missing."}
        return self.paynow_sdk.check_transaction_status(poll_url)
