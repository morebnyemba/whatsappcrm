# paynow_wrapper.py
import logging
import hashlib # Still needed for IPN verification
from decimal import Decimal
from typing import Dict, Any, Optional

from paynow import Paynow # Import the official SDK

logger = logging.getLogger(__name__)

class PaynowSDK: # This class will wrap the official Paynow SDK
    """ 
    A wrapper around the official Paynow Python SDK for Express Checkout.
    """
    def __init__(self, integration_id: str, integration_key: str, result_url: str, return_url: str):
        if not integration_id or not integration_key:
            raise ValueError("Paynow Integration ID and Key must be provided.")
        
        # The official SDK's Paynow constructor takes resulturl and returnurl.
        # These are the default URLs for payments created by this instance.
        self.paynow_instance = Paynow(integration_id, integration_key, result_url, return_url)
        self.integration_id = integration_id # Keep for IPN verification
        self.integration_key = integration_key # Keep for IPN verification
        logger.info(f"PaynowSDK wrapper initialized for Integration ID: {integration_id}")

    def initiate_express_checkout(
        self,
        amount: Decimal,
        reference: str,
        phone_number: str,
        email: str,
        paynow_method_type: str,
        description: str = "Wallet Deposit"
    ) -> Dict[str, Any]:
        """
        Initiates an Express Checkout payment using the official Paynow SDK.
        """
        try:
            # Create a payment object. The SDK's create_payment uses the result_url/return_url
            # set in the Paynow constructor unless explicitly overridden here.
            payment = self.paynow_instance.create_payment(
                reference,
                email
            )
            
            # Add the item (description and amount)
            payment.add(description, float(amount)) # SDK expects float for amount
            
            logger.info(f"PaynowSDK: Initiating Express Checkout for ref {reference}, amount {amount}, phone {phone_number}.")
            
            # Send the mobile payment request
            response = self.paynow_instance.send_mobile(payment, phone_number, paynow_method_type)
            
            logger.debug(f"PaynowSDK: API response: {response.__dict__}")

            if response.success:
                # For Express Checkout, there's no redirect_url.
                # The SDK returns instructions and a poll_url.
                paynow_reference = getattr(response, 'paynow_reference', None) # SDK might provide this
                poll_url = getattr(response, 'poll_url', None) # Important for status checks
                instructions = getattr(response, 'instructions', None) # Instructions for the user
                
                logger.info(f"PaynowSDK: Express Checkout initiated successfully. Paynow Reference: {paynow_reference}, Poll URL: {poll_url}")
                return {
                    "success": True,
                    "paynow_reference": paynow_reference,
                    "poll_url": poll_url, # Store this for later status checks
                    "instructions": instructions, # Display to user
                    "message": "Payment initiated successfully. Please check your phone for a prompt."
                }
            else:
                error_message = getattr(response, 'error', 'Unknown error from Paynow SDK.')
                logger.error(f"PaynowSDK: API returned an error: {error_message}. Full response: {response.__dict__}")
                return {"success": False, "message": f"Paynow error: {str(error_message)}"} # Ensure it's a string

        except Exception as e:
            logger.error(f"PaynowSDK: Unexpected error during Express Checkout initiation: {e}", exc_info=True)
            return {"success": False, "message": f"Internal error processing payment: {e}"}

    def verify_ipn_callback(self, ipn_data: Dict[str, str]) -> bool:
        """
        Verifies the integrity of an IPN callback from Paynow using the generated hash.
        The official SDK does not provide a direct IPN verification method,
        so we retain our manual hash verification logic.
        """
        hash_received = ipn_data.get('hash')
        
        status = ipn_data.get('status', '')
        reference = ipn_data.get('reference', '')
        paynow_reference = ipn_data.get('paynowreference', '')
        amount = ipn_data.get('amount', '')
        
        # The IPN hash calculation is specific and usually involves these fields + integration key.
        # This is based on common Paynow IPN documentation patterns.
        expected_hash_string = f"{status}{reference}{paynow_reference}{amount}{self.integration_key}"
        expected_hash = hashlib.md5(expected_hash_string.encode('utf-8')).hexdigest().upper()
        
        return hash_received == expected_hash

    def check_transaction_status(self, poll_url: str) -> Dict[str, Any]:
        """
        Checks the status of a transaction using the poll URL.
        """
        try:
            status_response = self.paynow_instance.check_transaction_status(poll_url)
            logger.debug(f"PaynowSDK: Status check response for {poll_url}: {status_response.__dict__}")
            
            return {
                "success": True,
                "status": status_response.status,
                "paid": status_response.paid,
                "hash_valid": status_response.hash_valid,
                "message": status_response.status # Use the status as a message
            }
        except Exception as e:
            logger.error(f"PaynowSDK: Error checking transaction status for {poll_url}: {e}", exc_info=True)
            return {"success": False, "message": f"Error checking status: {e}"}
