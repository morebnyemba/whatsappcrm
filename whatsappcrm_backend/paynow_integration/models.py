from django.db import models

class PaynowConfig(models.Model):
    """
    Stores Paynow API configuration details.
    There should typically be only one instance of this model.
    """
    integration_id = models.CharField(
        max_length=255,
        help_text="Your Paynow Integration ID (e.g., from Paynow dashboard)."
    )
    integration_key = models.CharField(
        max_length=255,
        help_text="Your Paynow Integration Key (e.g., from Paynow dashboard)."
    )
    # Base URL for Paynow API endpoints (e.g., 'https://www.paynow.co.zw/Interface/InitiateTransaction')
    api_base_url = models.URLField(
        default="https://www.paynow.co.zw/interface/remotetransaction", # Correct Express Checkout endpoint
        help_text="Base URL for Paynow API transactions."
    )

    class Meta:
        verbose_name = "Paynow Configuration"
        verbose_name_plural = "Paynow Configurations"

    def __str__(self):
        return "Paynow API Configuration"
