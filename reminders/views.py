import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import client
from .client import BotAPIError
from .forms import MappingForm, ReminderForm, member_label
from .models import AuditLog, GroupMapping, Reminder, log

logger = logging.getLogger(__name__)


# --- permissions ----------------------------------------------------------------

def user_group_dns(user):
    prof = getattr(user, "ldap", None)
    return {g.lower() for g in (prof.groups if prof else [])}


def visible_mappings(user):
    qs = GroupMapping.objects.filter(enabled=True)
    if user.is_staff:
        return GroupMapping.objects.all()
    dns = user_group_dns(user)
    return [m for m in qs if m.ldap_group_dn.lower() in dns]


def check_mapping(user, mapping):
    if user.is_staff:
        return
    if not mapping.enabled or mapping.ldap_group_dn.lower() not in user_group_dns(user):
        raise PermissionDenied(_("You are not a member of this group."))


# --- sync -------------------------------------------------------------------------

def push(reminder):
    """Push a reminder to signal-bot; records sync status. Returns True on success."""
    try:
        client.put_reminder(reminder.external_id, reminder.mapping.signal_group_id, reminder.spec,
                            reminder.enabled and reminder.mapping.enabled,
                            name=f"[{reminder.mapping}] {reminder.title}")
        reminder.sync_status, reminder.sync_error, reminder.synced_at = Reminder.Sync.OK, "", timezone.now()
    except BotAPIError as e:
        reminder.sync_status, reminder.sync_error = Reminder.Sync.ERROR, str(e)
    reminder.save(update_fields=["sync_status", "sync_error", "synced_at"])
    return reminder.sync_status == Reminder.Sync.OK


def members_for(mapping, spec=None):
    """Signal group members, plus people from an existing spec who aren't in the group anymore."""
    error = None
    try:
        members = client.members(mapping.signal_group_id)
    except BotAPIError as e:
        members, error = [], str(e)
    keys = {m.get("uuid") or m.get("number") for m in members}
    for p in (spec or {}).get("people", []):
        if (p.get("uuid") or p.get("number")) not in keys:
            members.append({**p, "label": _("%(name)s (not in group)") % {"name": member_label(p)}})
    return members, error


def refresh_names(spec, members):
    """Update the display names stored in a spec from the current Signal member list.
    Returns True if anything changed. Names are only for display; mentions use the UUID."""
    by_key = {m.get("uuid") or m.get("number"): m for m in members}
    changed = False
    for p in spec.get("people", []):
        m = by_key.get(p.get("uuid") or p.get("number"))
        name = (m or {}).get("name") or ""
        if name and name != p.get("name"):
            p["name"] = name
            changed = True
    return changed


def refresh_reminder_names(reminders, members):
    """Refresh names in stored reminders and push changed ones to signal-bot."""
    for r in reminders:
        if members and refresh_names(r.spec, members):
            r.save(update_fields=["spec"])
            push(r)


def next_dates(spec, n=3):
    try:
        return client.preview(spec, days=400)["items"][:n]
    except BotAPIError:
        return None


# --- user views ---------------------------------------------------------------------

def index(request):
    mappings = visible_mappings(request.user)
    if len(mappings) == 1 and not request.user.is_staff:
        return redirect("mapping_detail", pk=mappings[0].pk)
    return render(request, "reminders/index.html", {"mappings": mappings})


def mapping_detail(request, pk):
    mapping = get_object_or_404(GroupMapping, pk=pk)
    check_mapping(request.user, mapping)
    reminders = list(mapping.reminders.all())
    if reminders:
        members, _err = members_for(mapping)
        refresh_reminder_names(reminders, members)
    rows = [(r, next_dates(r.spec) if r.enabled else None) for r in reminders]
    return render(request, "reminders/mapping_detail.html", {"mapping": mapping, "rows": rows})


def _reminder_form_view(request, mapping, reminder=None):
    spec = reminder.spec if reminder else None
    members, members_error = members_for(mapping, spec)
    if reminder:
        refresh_reminder_names([reminder], members)
    if request.method == "POST":
        form = ReminderForm(request.POST, members=members)
        if form.is_valid():
            spec = form.cleaned_data["spec"]
            if "preview" in request.POST:
                try:
                    preview = client.preview(spec, days=120)
                except BotAPIError as e:
                    preview = {"error": str(e)}
                return render(request, "reminders/reminder_form.html", {
                    "form": form, "mapping": mapping, "reminder": reminder, "preview": preview,
                    "members_error": members_error})
            try:
                spec = client.preview(spec, days=1)["spec"]  # server-side validation/normalisation
            except BotAPIError as e:
                form.add_error(None, str(e))
            else:
                created = reminder is None
                if created:
                    reminder = Reminder(mapping=mapping, created_by=request.user)
                reminder.title = spec["title"]
                reminder.spec = spec
                reminder.enabled = form.cleaned_data["enabled"]
                reminder.updated_by = request.user
                reminder.save()
                log(request.user, "create" if created else "update", reminder, spec=spec, enabled=reminder.enabled)
                if push(reminder):
                    messages.success(request, _('Saved "%(title)s".') % {"title": reminder.title})
                else:
                    messages.error(request, _("Saved, but could not reach signal-bot: %(error)s") % {"error": reminder.sync_error})
                return redirect("mapping_detail", pk=mapping.pk)
    else:
        initial = ReminderForm.initial_from_spec(spec, reminder.enabled) if reminder else None
        form = ReminderForm(initial=initial, members=members)
    return render(request, "reminders/reminder_form.html", {
        "form": form, "mapping": mapping, "reminder": reminder, "members_error": members_error})


def reminder_new(request, mapping_pk):
    mapping = get_object_or_404(GroupMapping, pk=mapping_pk)
    check_mapping(request.user, mapping)
    return _reminder_form_view(request, mapping)


def reminder_edit(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk)
    check_mapping(request.user, reminder.mapping)
    return _reminder_form_view(request, reminder.mapping, reminder)


def reminder_copy(request, pk):
    src = get_object_or_404(Reminder, pk=pk)
    check_mapping(request.user, src.mapping)
    copy = Reminder(mapping=src.mapping, title=f"{src.title} (copy)", enabled=False,
                    spec={**src.spec, "title": f"{src.title} (copy)"}, created_by=request.user, updated_by=request.user)
    if request.method == "POST":
        copy.save()
        log(request.user, "copy", copy, source=str(src.external_id))
        push(copy)
        return redirect("reminder_edit", pk=copy.pk)
    return redirect("mapping_detail", pk=src.mapping.pk)


@require_POST
def reminder_delete(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk)
    check_mapping(request.user, reminder.mapping)
    try:
        client.delete_reminder(reminder.external_id)
    except BotAPIError as e:
        messages.error(request, _("Could not delete in signal-bot: %(error)s. Try again later.") % {"error": e})
        return redirect("mapping_detail", pk=reminder.mapping.pk)
    log(request.user, "delete", reminder, spec=reminder.spec)
    mapping_pk = reminder.mapping.pk
    reminder.delete()
    messages.success(request, _("Deleted."))
    return redirect("mapping_detail", pk=mapping_pk)


@require_POST
def reminder_toggle(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk)
    check_mapping(request.user, reminder.mapping)
    reminder.enabled = not reminder.enabled
    reminder.save(update_fields=["enabled"])
    log(request.user, "enable" if reminder.enabled else "disable", reminder)
    if not push(reminder):
        messages.error(request, _("Could not reach signal-bot: %(error)s") % {"error": reminder.sync_error})
    return redirect("mapping_detail", pk=reminder.mapping.pk)


@require_POST
def reminder_run(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk)
    check_mapping(request.user, reminder.mapping)
    try:
        if reminder.sync_status != Reminder.Sync.OK:
            push(reminder)
        client.run_reminder(reminder.external_id)
        log(request.user, "send_now", reminder)
        messages.success(request, _('"%(title)s" is being sent to %(group)s now.') % {"title": reminder.title, "group": reminder.mapping.signal_group_name})
    except BotAPIError as e:
        messages.error(request, _("Failed: %(error)s") % {"error": e})
    return redirect("mapping_detail", pk=reminder.mapping.pk)


def reminder_logs(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk)
    check_mapping(request.user, reminder.mapping)
    try:
        execs, error = client.executions(reminder.external_id), None
    except BotAPIError as e:
        execs, error = [], str(e)
    return render(request, "reminders/reminder_logs.html", {"reminder": reminder, "executions": execs, "error": error})


# --- admin views ------------------------------------------------------------------------

@staff_member_required
def admin_home(request):
    try:
        bot = client.status()
    except BotAPIError as e:
        bot = {"error": str(e)}
    unsynced = Reminder.objects.exclude(sync_status=Reminder.Sync.OK).count()
    return render(request, "reminders/admin_home.html", {
        "bot": bot, "mappings": GroupMapping.objects.all(), "unsynced": unsynced,
        "reminders": Reminder.objects.select_related("mapping").order_by("mapping__label", "title"),
        "audit": AuditLog.objects.select_related("user")[:30],
    })


def _mapping_form_sources():
    from .ldap_backend import list_groups
    errors = []
    try:
        ldap_groups = list_groups()
    except Exception as e:
        ldap_groups = []
        errors.append(f"LDAP: {e}")
    try:
        signal_groups = client.groups()
    except BotAPIError as e:
        signal_groups = []
        errors.append(f"signal-bot: {e}")
    return ldap_groups, signal_groups, errors


@staff_member_required
def mapping_edit(request, pk=None):
    mapping = get_object_or_404(GroupMapping, pk=pk) if pk else None
    ldap_groups, signal_groups, errors = _mapping_form_sources()
    # Keep current values selectable even if a source is unreachable.
    if mapping and not any(g["dn"] == mapping.ldap_group_dn for g in ldap_groups):
        ldap_groups.append({"dn": mapping.ldap_group_dn, "cn": mapping.ldap_group_cn, "members": []})
    if mapping and not any(g["id"] == mapping.signal_group_id for g in signal_groups):
        signal_groups.append({"id": mapping.signal_group_id, "name": mapping.signal_group_name})
    if request.method == "POST":
        form = MappingForm(request.POST, ldap_groups=ldap_groups, signal_groups=signal_groups)
        if form.is_valid():
            c = form.cleaned_data
            mapping = mapping or GroupMapping(created_by=request.user)
            mapping.ldap_group_dn = c["ldap_group_dn"]
            mapping.signal_group_id = c["signal_group_id"]
            mapping.signal_group_name = next((g["name"] for g in signal_groups if g["id"] == c["signal_group_id"]), "")
            mapping.label = c["label"]
            mapping.enabled = c["enabled"]
            mapping.save()
            log(request.user, "mapping_save", mapping, ldap=mapping.ldap_group_dn, signal=mapping.signal_group_name)
            for r in mapping.reminders.all():  # group or enabled state may have changed
                push(r)
            messages.success(request, _("Mapping saved."))
            return redirect("mapping_members", pk=mapping.pk)
    else:
        form = MappingForm(initial={
            "ldap_group_dn": mapping.ldap_group_dn, "signal_group_id": mapping.signal_group_id,
            "label": mapping.label, "enabled": mapping.enabled} if mapping else {"enabled": True},
            ldap_groups=ldap_groups, signal_groups=signal_groups)
    return render(request, "reminders/mapping_form.html", {"form": form, "mapping": mapping, "errors": errors})


@staff_member_required
@require_POST
def mapping_delete(request, pk):
    mapping = get_object_or_404(GroupMapping, pk=pk)
    if mapping.reminders.exists():
        messages.error(request, _("Delete or move its reminders first (or just disable the mapping)."))
        return redirect("admin_home")
    log(request.user, "mapping_delete", mapping)
    mapping.delete()
    return redirect("admin_home")


@staff_member_required
def mapping_members(request, pk):
    """LDAP group members vs. Signal group members, side by side."""
    mapping = get_object_or_404(GroupMapping, pk=pk)
    errors = []
    ldap_names = []
    try:
        from .ldap_backend import describe_users, list_groups
        grp = next((g for g in list_groups() if g["dn"].lower() == mapping.ldap_group_dn.lower()), None)
        if grp is None:
            errors.append(_("LDAP group not found."))
        else:
            ldap_names = sorted(describe_users(grp["members"]).values(), key=str.lower)
    except Exception as e:
        errors.append(f"LDAP: {e}")
    signal_members, err = members_for(mapping)
    if err:
        errors.append(f"signal-bot: {err}")
    signal_names = sorted((member_label(m) for m in signal_members), key=str.lower)

    def first(n):
        return n.split()[0].lower() if n.split() else ""
    sig_first = {first(n) for n in signal_names}
    ldap_first = {first(n) for n in ldap_names}
    return render(request, "reminders/mapping_members.html", {
        "mapping": mapping, "errors": errors,
        "ldap_rows": [(n, first(n) in sig_first) for n in ldap_names],
        "signal_rows": [(n, first(n) in ldap_first) for n in signal_names],
    })


@staff_member_required
@require_POST
def resync_all(request):
    for mapping in GroupMapping.objects.all():
        reminders = list(mapping.reminders.all())
        if reminders:
            members, _err = members_for(mapping)
            for r in reminders:
                if members:
                    refresh_names(r.spec, members)
                    r.save(update_fields=["spec"])
    ok = sum(push(r) for r in Reminder.objects.select_related("mapping"))
    removed = 0
    try:
        known = {str(r.external_id) for r in Reminder.objects.all()}
        for remote in client.list_reminders():
            if remote["external_id"] not in known:
                client.delete_reminder(remote["external_id"])
                removed += 1
    except BotAPIError as e:
        messages.error(request, _("Cleanup failed: %(error)s") % {"error": e})
    log(request.user, "resync_all", "all", pushed=ok, removed=removed)
    messages.success(request, _("Pushed %(ok)d reminder(s), removed %(removed)d orphaned job(s) in signal-bot.") % {"ok": ok, "removed": removed})
    return redirect("admin_home")


@staff_member_required
@require_POST
def sync_signal_groups(request):
    try:
        client.sync_groups()
        messages.success(request, _("signal-bot is refreshing its group list (takes a few seconds)."))
    except BotAPIError as e:
        messages.error(request, str(e))
    nxt = request.POST.get("next") or ""
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "admin_home")
