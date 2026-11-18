import re
from datetime import date

from django import forms

DEFAULT_TEMPLATE = 'Hey {mentions}, eine Erinnerung für "{title}" – {timing} :)'

WEEKDAYS = [(0, "Mo"), (1, "Di"), (2, "Mi"), (3, "Do"), (4, "Fr"), (5, "Sa"), (6, "So")]
MONTHS = [(i, n) for i, n in enumerate(
    ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"], start=1)]
SCHEDULE_TYPES = [
    ("weekly", "Weekly (on certain weekdays)"),
    ("monthly", "Monthly (on a day of the month)"),
    ("interval", "Every N days (e.g. every 2 weeks)"),
    ("dates", "List of specific dates (e.g. a rota)"),
    ("once", "Once"),
]
DATE_LINE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{2,4})\s*[:\-–]?\s*(.*)$")


def parse_date(s):
    s = s.strip()
    if "-" in s:
        return date.fromisoformat(s)
    d, m, y = s.split(".")
    y = int(y)
    if y < 100:
        y += 2000
    return date(y, int(m), int(d))




def member_label(m):
    """What users see for a Signal member: name, else number, else a short anonymous tag (never a full UUID)."""
    if m.get("label"):
        return m["label"]
    if (m.get("name") or "").strip():
        return m["name"].strip()
    if m.get("number"):
        return m["number"]
    uid = m.get("uuid") or ""
    return f"Unbekanntes Mitglied (…{uid[-6:]})" if uid else "Unbekanntes Mitglied"

class MappingForm(forms.Form):
    ldap_group_dn = forms.ChoiceField(label="LDAP group")
    signal_group_id = forms.ChoiceField(label="Signal group")
    label = forms.CharField(required=False, max_length=200, help_text="Optional display name")
    enabled = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, ldap_groups=(), signal_groups=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ldap_group_dn"].choices = [(g["dn"], f'{g["cn"]}  ({g["dn"]}, {len(g["members"])} members)') for g in ldap_groups]
        self.fields["signal_group_id"].choices = [(g["id"], g["name"] or g["id"]) for g in signal_groups]


class ReminderForm(forms.Form):
    title = forms.CharField(max_length=200, help_text='Used as {title} in the message, e.g. "Mülldienst"')
    people = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple,
                                       help_text="Who gets @mentioned. Members of the Signal group.")
    assignment = forms.ChoiceField(choices=[("all", "Mention everyone selected every time"),
                                            ("rotate", "Rotate: one person per occurrence, in the order above")],
                                   initial="all", widget=forms.RadioSelect)
    schedule_type = forms.ChoiceField(choices=SCHEDULE_TYPES, initial="weekly")
    weekdays = forms.TypedMultipleChoiceField(choices=WEEKDAYS, coerce=int, required=False,
                                              widget=forms.CheckboxSelectMultiple)
    every_weeks = forms.IntegerField(min_value=1, max_value=52, initial=1, required=False,
                                     help_text="1 = every week, 2 = every other week (needs a start date)")
    day_of_month = forms.IntegerField(min_value=1, max_value=31, initial=1, required=False,
                                      help_text="31 = last day of the month")
    months = forms.TypedMultipleChoiceField(choices=MONTHS, coerce=int, required=False,
                                            widget=forms.CheckboxSelectMultiple,
                                            help_text="Leave empty for every month")
    every_days = forms.IntegerField(min_value=1, max_value=366, initial=14, required=False)
    once_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    dates_text = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 8, "placeholder": "09.11.2026 Leon\n23.11.2026 Lilli\n07.12.2026"}),
        help_text="One date per line, optionally followed by the name(s) responsible that day (comma separated). "
                  "Without names, the selected people/rotation apply.")
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}),
                            help_text="First date (required for 'every N days'; rotation starts here)")
    until = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}),
                            help_text="Optional: stop after this date")
    lead_days = forms.IntegerField(min_value=0, max_value=60, initial=0,
                                   help_text="Send the reminder this many days before the date (0 = on the day)")
    send_time = forms.TimeField(initial="09:00", widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    message_template = forms.CharField(
        initial=DEFAULT_TEMPLATE, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Placeholders: {mentions} {names} {title} {date} {weekday} {days_until} {timing}")
    enabled = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, members=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.members = list(members)
        self.fields["people"].choices = [(self._key(m), member_label(m)) for m in self.members]

    @staticmethod
    def _key(m):
        return m.get("uuid") or m.get("number") or m.get("name")

    def _person(self, key):
        for m in self.members:
            if self._key(m) == key:
                return {k: m[k] for k in ("uuid", "number", "name") if m.get(k)}
        return None

    def _match_name(self, name, people):
        n = name.strip().lower()
        if not n:
            return None
        pool = people + [p for p in (self._person(self._key(m)) for m in self.members) if p not in people]
        exact = [p for p in pool if (p.get("name") or "").lower() == n]
        if exact:
            return exact[0]
        starts = [p for p in pool if any(part.startswith(n) for part in (p.get("name") or "").lower().split())
                  or (p.get("name") or "").lower().startswith(n)]
        return starts[0] if len(starts) == 1 else None

    def clean(self):
        c = super().clean()
        if self.errors:
            return c
        people = [p for p in (self._person(k) for k in c.get("people") or []) if p]
        st = c["schedule_type"]
        sched = {"type": st}
        if c.get("start"):
            sched["start"] = c["start"].isoformat()
        if c.get("until"):
            sched["until"] = c["until"].isoformat()
        if st == "weekly":
            if not c.get("weekdays"):
                self.add_error("weekdays", "Pick at least one weekday.")
            sched["weekdays"] = c.get("weekdays") or []
            sched["every_weeks"] = c.get("every_weeks") or 1
            if sched["every_weeks"] > 1 and not c.get("start"):
                self.add_error("start", "Needed when not every week.")
        elif st == "monthly":
            sched["day_of_month"] = c.get("day_of_month") or 1
            if c.get("months"):
                sched["months"] = c["months"]
        elif st == "interval":
            sched["every_days"] = c.get("every_days") or 14
            if not c.get("start"):
                self.add_error("start", "Needed for 'every N days'.")
        elif st == "once":
            if not c.get("once_date"):
                self.add_error("once_date", "Pick the date.")
            else:
                sched["date"] = c["once_date"].isoformat()
        elif st == "dates":
            entries, extra_people = [], []
            for i, line in enumerate((c.get("dates_text") or "").splitlines(), start=1):
                if not line.strip():
                    continue
                m = DATE_LINE.match(line)
                if not m:
                    self.add_error("dates_text", f"Line {i}: can't read '{line.strip()}' (use 09.11.2026 or 2026-11-09).")
                    continue
                try:
                    d = parse_date(m.group(1))
                except ValueError:
                    self.add_error("dates_text", f"Line {i}: invalid date '{m.group(1)}'.")
                    continue
                entry = {"date": d.isoformat()}
                names = [n for n in re.split(r"[,&/]| und ", m.group(2)) if n.strip()]
                if names:
                    keys = []
                    for n in names:
                        p = self._match_name(n, people)
                        if not p:
                            self.add_error("dates_text", f"Line {i}: no unique group member matches '{n.strip()}'.")
                            continue
                        keys.append(self._key(p))
                        if p not in people and p not in extra_people:
                            extra_people.append(p)
                    entry["people"] = keys
                entries.append(entry)
            if not entries and not self.has_error("dates_text"):
                self.add_error("dates_text", "Enter at least one date.")
            sched["dates"] = entries
            people = people + extra_people
        if c.get("assignment") == "rotate" and not people and st != "dates":
            self.add_error("people", "Rotation needs at least one person.")
        c["spec"] = {
            "version": 1,
            "title": c["title"],
            "message_template": c["message_template"],
            "send_time": c["send_time"].strftime("%H:%M"),
            "people": people,
            "assignment": c["assignment"],
            "lead_days": c["lead_days"],
            "schedule": sched,
        }
        return c

    @classmethod
    def initial_from_spec(cls, spec, enabled=True):
        s = spec.get("schedule", {})
        by_key = {cls._key(p): p for p in spec.get("people", [])}
        lines = []
        for e in s.get("dates", []):
            d = date.fromisoformat(e["date"]).strftime("%d.%m.%Y")
            names = [member_label(by_key.get(k) or {"uuid": k}) for k in e.get("people", [])]
            lines.append(f"{d} {', '.join(names)}".strip())
        # People named only on specific dates aren't "selected" for the general rotation.
        dated = {k for e in s.get("dates", []) for k in e.get("people", [])}
        selected = [cls._key(p) for p in spec.get("people", []) if s.get("type") != "dates" or cls._key(p) not in dated]
        return {
            "title": spec.get("title", ""),
            "people": selected,
            "assignment": spec.get("assignment", "all"),
            "schedule_type": s.get("type", "weekly"),
            "weekdays": s.get("weekdays", []),
            "every_weeks": s.get("every_weeks", 1),
            "day_of_month": s.get("day_of_month", 1),
            "months": s.get("months", []),
            "every_days": s.get("every_days", 14),
            "once_date": s.get("date"),
            "dates_text": "\n".join(lines),
            "start": s.get("start"),
            "until": s.get("until"),
            "lead_days": spec.get("lead_days", 0),
            "send_time": spec.get("send_time", "09:00"),
            "message_template": spec.get("message_template", DEFAULT_TEMPLATE),
            "enabled": enabled,
        }
