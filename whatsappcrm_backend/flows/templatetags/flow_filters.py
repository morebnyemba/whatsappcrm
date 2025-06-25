# whatsappcrm_backend/flows/templatetags/flow_filters.py
from django import template

register = template.Library()

@register.filter(name='float')
def to_float(value):
    """Converts a value to a float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        # Return 0.0 or the original value if conversion fails
        return 0.0