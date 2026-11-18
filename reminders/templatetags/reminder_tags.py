from django import template
from django.utils.translation import gettext as _

register = template.Library()

@register.filter
def schedule_label(spec):
    """Short, translated name of a spec's schedule type."""
    t = (spec or {}).get("schedule", {}).get("type", "")
    labels = {"weekly": _("weekly"), "monthly": _("monthly"), "interval": _("every N days"),
              "dates": _("date list"), "once": _("once")}
    return labels.get(t, t)


@register.filter
def sync_label(status):
    return {"ok": _("synced"), "error": _("not synced"), "pending": _("pending"),
            "success": _("success"), "failed": _("failed"), "running": _("running")}.get(status, status)
