"""Convert signal-bot's legacy putztasks.json into reminders for one group mapping.

    uv run python manage.py import_putztasks putztasks.json --mapping 1 [--season-start 2026] [--apply]

Without --apply it only prints what it would create (plus a preview of the next messages).
Rules, mirroring scripts/putztask_reminder.py:
  * "weekday": weekly on that day, everyone, on the day itself
  * no schedule: monthly on the 1st, everyone
  * "DD.MM" entries: list of dates with the named assignee (or everyone), 4 days ahead
  * month-name entries ("Dezember"): on the 15th of that month, on the day
Names are matched once against the Signal group's member names (same fuzzy rules as the
old script); review the printed matches before --apply.
"""

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from reminders import client
from reminders.models import GroupMapping, Reminder, log
from reminders.views import push

MONTHS = {"januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
          "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
TEMPLATE = 'Hey {mentions}, eine Erinnerung für die Task "{title}" – {timing} :)'


def _part_matches(q, f):
    abbrev = q.endswith(".")
    q, f = q.rstrip("."), f.rstrip(".")
    if not q or not f or (not abbrev and (len(q) < 2 or len(f) < 2)):
        return False
    return q.startswith(f) or f.startswith(q)


def match_member(name, members):
    n = name.lower()
    best, best_score = None, -1
    for m in members:
        full = (m.get("name") or "").lower()
        if len(full) < 2:
            continue
        if n == full:
            return m
        matched = overlap = 0
        for np in n.split():
            for fp in full.split():
                if _part_matches(np, fp):
                    matched += 1
                    overlap += min(len(np.rstrip(".")), len(fp.rstrip(".")))
                    break
        if matched == len(n.split()) and matched:
            score = overlap * 10 + matched
            if score > best_score:
                best, best_score = m, score
    return best


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--mapping", type=int, required=True, help="GroupMapping id")
        parser.add_argument("--season-start", type=int, default=None,
                            help="Year of the season's first months (Aug-Dec). Default: current season.")
        parser.add_argument("--send-time", default="09:00")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, file, mapping, season_start, send_time, apply, **kw):
        try:
            m = GroupMapping.objects.get(pk=mapping)
        except GroupMapping.DoesNotExist:
            raise CommandError("unknown mapping")
        today = date.today()
        y0 = season_start or (today.year if today.month >= 8 else today.year - 1)
        year_for = lambda month: y0 if month >= 8 else y0 + 1  # noqa: E731
        members = client.members(m.signal_group_id)
        data = json.load(open(file, encoding="utf-8"))

        cache = {}

        def person(name):
            if name not in cache:
                hit = match_member(name, members)
                cache[name] = ({k: hit[k] for k in ("uuid", "number", "name") if hit.get(k)} if hit else {"name": name})
                self.stdout.write(f"  match {name!r:24} -> {hit['name'] if hit else 'NO MATCH (plain name, no @mention)'}")
            return cache[name]

        def key(p):
            return p.get("uuid") or p.get("number") or p.get("name")

        specs = []
        for task in data["tasks"]:
            title = task["task"]
            people = [person(a) for a in task["assignees"]]
            base = {"version": 1, "title": title, "message_template": TEMPLATE, "send_time": send_time,
                    "people": people, "assignment": "all", "lead_days": 0}
            sched = task.get("schedule") or []
            if task.get("weekday"):
                spec = {**base, "schedule": {"type": "weekly", "weekdays": [WEEKDAYS[task["weekday"].lower()]]}}
            elif not sched:
                spec = {**base, "schedule": {"type": "monthly", "day_of_month": 1}}
            else:
                dates, month_only = [], False
                for e in sched:
                    raw = e["date"].strip()
                    if raw.lower() in MONTHS:
                        month_only = True
                        mo = MONTHS[raw.lower()]
                        d = date(year_for(mo), mo, 15)
                    else:
                        dd, mo = (int(x) for x in raw.split(".")[:2])
                        d = date(year_for(mo), mo, dd)
                    entry = {"date": d.isoformat()}
                    if e.get("assignee"):
                        p = person(e["assignee"])
                        if p not in people:
                            people.append(p)
                        entry["people"] = [key(p)]
                    dates.append(entry)
                lead = 0 if (month_only or title.lower() == "tafel") else 4
                spec = {**base, "people": people, "lead_days": lead, "schedule": {"type": "dates", "dates": dates}}
            specs.append(spec)

        for spec in specs:
            res = client.preview(spec, days=120)
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{spec['title']}") +
                              f"  [{spec['schedule']['type']}, lead {spec['lead_days']}d]")
            for i in res["items"][:3]:
                self.stdout.write(f"   {i['send_on']}: {i['text']}")
            if apply:
                r = Reminder.objects.create(mapping=m, title=spec["title"], spec=res["spec"], enabled=True)
                log(None, "import", r, source="putztasks.json")
                self.stdout.write(f"   -> created, sync {'ok' if push(r) else 'FAILED: ' + r.sync_error}")
        if not apply:
            self.stdout.write(self.style.WARNING("\nDry run. Re-run with --apply to create the reminders."))
