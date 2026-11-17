"""Minimal LDAP auth backend (ldap3, no C deps).

Flow (same as smartdormv2's django-auth-ldap config): bind with the service account,
find the user by ``(cn=<username>)`` under LDAP_USER_BASE, re-bind as that DN with the given
password, then collect ``groupOfNames`` groups whose ``member`` is the user's DN.
The user's group DNs are stored in ``LdapProfile.groups`` and refreshed at every login.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from ldap3 import BASE, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

logger = logging.getLogger(__name__)


def _server():
    return Server(settings.LDAP_URI, connect_timeout=settings.LDAP_TIMEOUT)


def service_connection():
    conn = Connection(
        _server(), user=settings.LDAP_BIND_DN, password=settings.LDAP_BIND_PASSWORD,
        receive_timeout=settings.LDAP_TIMEOUT, raise_exceptions=True,
    )
    conn.open()
    if settings.LDAP_START_TLS:
        conn.start_tls()
    conn.bind()
    return conn


def _first(entry, attr):
    v = entry.get("attributes", {}).get(attr)
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def find_user(conn, username):
    flt = f"({settings.LDAP_USER_ATTR}={escape_filter_chars(username)})"
    conn.search(settings.LDAP_USER_BASE, flt, SUBTREE,
                attributes=["cn", "uid", "mail", "givenName", "sn", "displayName"])
    entries = [e for e in conn.response if e.get("type") == "searchResEntry"]
    return entries[0] if len(entries) == 1 else None


def user_groups(conn, user_dn):
    groups = []
    flt = f"(&(objectClass=groupOfNames)(member={escape_filter_chars(user_dn)}))"
    for base in settings.LDAP_GROUP_BASES:
        try:
            conn.search(base, flt, SUBTREE, attributes=["cn"])
        except LDAPException as e:
            logger.warning("group search in %s failed: %s", base, e)
            continue
        groups += [e["dn"] for e in conn.response if e.get("type") == "searchResEntry"]
    return groups


def list_groups():
    """All groupOfNames groups in the configured bases: [{dn, cn, members:[dn]}]."""
    conn = service_connection()
    try:
        res = []
        for base in settings.LDAP_GROUP_BASES:
            conn.search(base, "(objectClass=groupOfNames)", SUBTREE, attributes=["cn", "member"])
            for e in conn.response:
                if e.get("type") == "searchResEntry":
                    res.append({"dn": e["dn"], "cn": _first(e, "cn"),
                                "members": e["attributes"].get("member", [])})
        return sorted(res, key=lambda g: g["dn"].lower())
    finally:
        conn.unbind()


def describe_users(dns):
    """Map user DNs to display names (best effort)."""
    conn = service_connection()
    out = {}
    try:
        for dn in dns:
            try:
                conn.search(dn, "(objectClass=*)", BASE, attributes=["cn", "givenName", "sn", "displayName"])
                e = next((x for x in conn.response if x.get("type") == "searchResEntry"), None)
            except LDAPException:
                e = None
            if e:
                name = _first(e, "displayName") or " ".join(
                    x for x in (_first(e, "givenName"), _first(e, "sn")) if x) or _first(e, "cn")
                out[dn] = name
            else:
                out[dn] = dn.split(",")[0].split("=")[-1]
        return out
    finally:
        conn.unbind()


class LDAPBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password or not settings.LDAP_BIND_DN:
            return None
        try:
            conn = service_connection()
        except LDAPException as e:
            logger.error("LDAP service bind failed: %s", e)
            return None
        try:
            entry = find_user(conn, username)
            if not entry:
                return None
            user_dn = entry["dn"]
            try:
                uconn = Connection(_server(), user=user_dn, password=password,
                                   receive_timeout=settings.LDAP_TIMEOUT, raise_exceptions=True)
                uconn.open()
                if settings.LDAP_START_TLS:
                    uconn.start_tls()
                uconn.bind()
                uconn.unbind()
            except LDAPException:
                return None
            groups = user_groups(conn, user_dn)
        finally:
            conn.unbind()

        User = get_user_model()
        user, _ = User.objects.get_or_create(username=f"ldap:{username}")
        user.first_name = (_first(entry, "givenName") or _first(entry, "displayName") or username)[:150]
        user.last_name = _first(entry, "sn")[:150]
        user.email = _first(entry, "mail")[:254]
        user.is_staff = any(g.lower() in settings.LDAP_ADMIN_GROUPS for g in groups)
        user.set_unusable_password()
        user.save()

        from reminders.models import LdapProfile
        LdapProfile.objects.update_or_create(user=user, defaults={"dn": user_dn, "groups": groups})
        return user

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
