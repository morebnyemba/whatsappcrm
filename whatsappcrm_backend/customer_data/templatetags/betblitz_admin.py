# whatsappcrm_backend/customer_data/templatetags/betblitz_admin.py
"""Template tags backing the custom admin dashboard (templates/admin/index.html)."""
from django import template

from customer_data.dashboard import get_dashboard_stats

register = template.Library()


@register.simple_tag
def dashboard_stats():
    """KPI payload for the admin dashboard.

    Used as `{% dashboard_stats as stats %}` so the index template can render
    the operator KPI cards without needing a custom AdminSite subclass.
    """
    return get_dashboard_stats()
