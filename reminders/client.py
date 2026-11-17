"""Thin client for signal-bot's /api/v1."""

from urllib.parse import quote

import requests
from django.conf import settings


class BotAPIError(Exception):
    pass


def _req(method, path, json=None, params=None, timeout=20):
    url = settings.SIGNAL_BOT_API_URL + path
    try:
        r = requests.request(method, url, json=json, params=params, timeout=timeout,
                             headers={"Authorization": f"Bearer {settings.SIGNAL_BOT_API_TOKEN}"})
    except requests.RequestException as e:
        raise BotAPIError(f"signal-bot not reachable: {e}")
    try:
        data = r.json()
    except ValueError:
        raise BotAPIError(f"signal-bot returned HTTP {r.status_code}")
    if r.status_code >= 400:
        raise BotAPIError(data.get("error") or f"HTTP {r.status_code}")
    return data


def status():
    return _req("GET", "/status/")


def groups():
    return _req("GET", "/groups/")["groups"]


def sync_groups():
    return _req("POST", "/groups/sync/")


def members(group_id):
    return _req("GET", "/groups/members/", params={"id": group_id}, timeout=60)["members"]


def preview(spec, start=None, days=60):
    body = {"spec": spec, "days": days}
    if start:
        body["from"] = start
    return _req("POST", "/preview/", json=body)


def list_reminders():
    return _req("GET", "/reminders/")["reminders"]


def put_reminder(external_id, group_id, spec, enabled, name=None):
    return _req("PUT", f"/reminders/{quote(str(external_id))}/",
                json={"group_id": group_id, "spec": spec, "enabled": enabled, "name": name})


def delete_reminder(external_id):
    return _req("DELETE", f"/reminders/{quote(str(external_id))}/")


def run_reminder(external_id):
    return _req("POST", f"/reminders/{quote(str(external_id))}/run/")


def executions(external_id):
    return _req("GET", f"/reminders/{quote(str(external_id))}/executions/")["executions"]
