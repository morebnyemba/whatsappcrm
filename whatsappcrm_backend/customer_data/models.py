# whatsappcrm_backend/customer_data/models.py

from django.db import models
from django.utils.translation import gettext_lazy as _
# Link to the Contact model from the conversations app
from conversations.models import Contact

class CustomerProfile(models.Model):
    """
    Stores aggregated and specific data about a customer, linked to their Contact record.
    This profile is enriched over time through conversations and flow interactions.
    """
    contact = models.OneToOneField(
        Contact,
        on_delete=models.CASCADE,
        related_name='customer_profile',
        primary_key=True, # Makes contact_id the primary key for this table
        help_text=_("The contact this profile belongs to.")
    )
    
    # Personal Details
    first_name = models.CharField(_("First Name"), max_length=100, blank=True, null=True)
    last_name = models.CharField(_("Last Name"), max_length=100, blank=True, null=True)
    email = models.EmailField(
        _("Email Address"),
        max_length=254,
        blank=True,
        null=True,
    )
    secondary_phone_number = models.CharField(
        _("Secondary Phone"), 
        max_length=30, 
        blank=True, 
        null=True,
        help_text=_("An alternative phone number, if provided.")
    )
    date_of_birth = models.DateField(_("Date of Birth"), null=True, blank=True)
    GENDER_CHOICES = [
        ('male', _('Male')),
        ('female', _('Female')),
        ('other', _('Other')),
        ('prefer_not_to_say', _('Prefer not to say')),
    ]
    gender = models.CharField(
        _("Gender"),
        max_length=20,
        choices=GENDER_CHOICES,
        blank=True,
        null=True
    )

    # Professional Details
    company_name = models.CharField(_("Company Name"), max_length=255, blank=True, null=True)
    job_title = models.CharField(_("Job Title"), max_length=255, blank=True, null=True)

    # Location Details
    address_line_1 = models.CharField(_("Address Line 1"), max_length=255, blank=True, null=True)
    address_line_2 = models.CharField(_("Address Line 2"), max_length=255, blank=True, null=True)
    city = models.CharField(_("City"), max_length=100, blank=True, null=True)
    state_province = models.CharField(_("State/Province"), max_length=100, blank=True, null=True)
    postal_code = models.CharField(_("Postal Code"), max_length=20, blank=True, null=True)
    country = models.CharField(_("Country"), max_length=100, blank=True, null=True)

    # CRM Specifics
    LIFECYCLE_STAGE_CHOICES = [
        ('lead', _('Lead')),
        ('opportunity', _('Opportunity')),
        ('customer', _('Customer')),
        ('vip', _('VIP Customer')),
        ('churned', _('Churned')),
        ('other', _('Other')),
    ]
    lifecycle_stage = models.CharField(
        _("Lifecycle Stage"),
        max_length=50,
        choices=LIFECYCLE_STAGE_CHOICES,
        blank=True,
        null=True,
        default='lead'
    )
    acquisition_source = models.CharField(
        _("Acquisition Source"),
        max_length=150, 
        blank=True, 
        null=True, 
        help_text=_("How this customer was acquired, e.g., 'Ad Campaign X', 'Website Signup', 'Referral'")
    )
    tags = models.JSONField( # List of strings
        _("Tags"),
        default=list, 
        blank=True, 
        help_text=_("Descriptive tags for segmentation, e.g., ['product_x_interest', 'webinar_attendee']")
    )
    notes = models.TextField(
        _("Notes"), 
        blank=True, 
        null=True,
        help_text=_("General notes about the customer.")
    )

    # Flexible JSON fields for data collected via flows or integrations
    preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Customer preferences collected over time (e.g., language, interests).")
    )
    custom_attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Arbitrary custom attributes collected for this customer.")
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, help_text=_("Last time this profile record was updated."))
    last_updated_from_conversation = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text=_("Last time data was explicitly updated from a conversation/flow.")
    )

    def get_full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        return None

    def __str__(self):
        full_name = self.get_full_name()
        if full_name:
            return f"Profile for {full_name} ({self.contact.whatsapp_id})"
        return f"Profile for {self.contact.name or self.contact.whatsapp_id}"

    class Meta:
        verbose_name = _("Customer Profile")
        verbose_name_plural = _("Customer Profiles")
        ordering = ['-updated_at']
