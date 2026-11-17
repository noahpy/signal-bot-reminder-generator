from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from .forms import ReminderForm
from .models import GroupMapping, LdapProfile, Reminder

MEMBERS = [{"uuid": "u1", "name": "Leon Fischer"}, {"uuid": "u2", "name": "Lilli M"}, {"uuid": "u3", "name": "Adi"}]
FLOOR = "cn=flur_h2f4,ou=roles,dc=schollheim,dc=net"


def form_data(**kw):
    d = {"title": "Staubsaugbeutel", "assignment": "all", "schedule_type": "weekly", "weekdays": ["3"],
         "every_weeks": "1", "lead_days": "0", "send_time": "09:00",
         "message_template": "Hey {mentions} {timing}", "enabled": "on"}
    d.update(kw)
    return d


class FormTests(TestCase):
    def test_weekly(self):
        f = ReminderForm(form_data(people=["u1", "u2"]), members=MEMBERS)
        self.assertTrue(f.is_valid(), f.errors)
        spec = f.cleaned_data["spec"]
        self.assertEqual(spec["schedule"], {"type": "weekly", "weekdays": [3], "every_weeks": 1})
        self.assertEqual([p["name"] for p in spec["people"]], ["Leon Fischer", "Lilli M"])

    def test_dates_with_names_roundtrip(self):
        f = ReminderForm(form_data(schedule_type="dates", lead_days="4",
                                   dates_text="09.11.2026 Leon\n2026-11-23: Lilli, Adi\n07.12.26"), members=MEMBERS)
        self.assertTrue(f.is_valid(), f.errors)
        spec = f.cleaned_data["spec"]
        self.assertEqual(spec["schedule"]["dates"], [
            {"date": "2026-11-09", "people": ["u1"]}, {"date": "2026-11-23", "people": ["u2", "u3"]},
            {"date": "2026-12-07"}])
        initial = ReminderForm.initial_from_spec(spec)
        self.assertEqual(initial["dates_text"], "09.11.2026 Leon Fischer\n23.11.2026 Lilli M, Adi\n07.12.2026")

    def test_errors(self):
        f = ReminderForm(form_data(schedule_type="dates", dates_text="32.13.2026 Bob"), members=MEMBERS)
        self.assertFalse(f.is_valid())
        f = ReminderForm(form_data(schedule_type="interval"), members=MEMBERS)
        self.assertIn("start", f.errors)
        f = ReminderForm(form_data(assignment="rotate"), members=MEMBERS)
        self.assertIn("people", f.errors)


@mock.patch("reminders.views.client")
class ViewTests(TestCase):
    def setUp(self):
        self.m = GroupMapping.objects.create(ldap_group_dn=FLOOR, signal_group_id="g1", signal_group_name="H2F4")
        self.other = GroupMapping.objects.create(ldap_group_dn="cn=x,ou=roles,dc=schollheim,dc=net",
                                                 signal_group_id="g2", signal_group_name="Other")
        self.user = User.objects.create_user("ldap:a.mozart", password="pw")
        LdapProfile.objects.create(user=self.user, dn="cn=a.mozart,ou=users", groups=[FLOOR.upper()])
        self.client.login(username="ldap:a.mozart", password="pw")

    def test_permissions(self, client):
        client.preview.return_value = {"items": []}
        self.assertEqual(self.client.get(f"/groups/{self.m.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/groups/{self.other.pk}/").status_code, 403)
        self.assertEqual(self.client.get("/manage/").status_code, 302)

    def test_create_pushes(self, client):
        client.members.return_value = MEMBERS
        client.preview.side_effect = lambda spec, days=60: {"spec": spec, "items": []}
        r = self.client.post(f"/groups/{self.m.pk}/new/", form_data(people=["u1"]))
        self.assertEqual(r.status_code, 302)
        rem = Reminder.objects.get()
        self.assertEqual(rem.sync_status, "ok")
        args = client.put_reminder.call_args[0]
        self.assertEqual((args[0], args[1]), (rem.external_id, "g1"))
