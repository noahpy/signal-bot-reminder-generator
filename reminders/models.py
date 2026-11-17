import uuid

from django.conf import settings
from django.db import models


class LdapProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ldap")
    dn = models.CharField(max_length=500)
    groups = models.JSONField(default=list)  # group DNs, refreshed at login
    updated_at = models.DateTimeField(auto_now=True)


class GroupMapping(models.Model):
    """An LDAP group whose members may manage reminders for a Signal group."""
    ldap_group_dn = models.CharField(max_length=500)
    signal_group_id = models.CharField(max_length=200)
    signal_group_name = models.CharField(max_length=200, blank=True)
    label = models.CharField(max_length=200, blank=True, help_text="Display name, e.g. 'H2F4 Putzplan'")
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label", "signal_group_name"]
        unique_together = [("ldap_group_dn", "signal_group_id")]

    @property
    def ldap_group_cn(self):
        return self.ldap_group_dn.split(",")[0].split("=")[-1]

    def __str__(self):
        return self.label or f"{self.ldap_group_cn} → {self.signal_group_name}"


class Reminder(models.Model):
    class Sync(models.TextChoices):
        PENDING = "pending"
        OK = "ok"
        ERROR = "error"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    mapping = models.ForeignKey(GroupMapping, on_delete=models.PROTECT, related_name="reminders")
    title = models.CharField(max_length=200)
    spec = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sync_status = models.CharField(max_length=10, choices=Sync.choices, default=Sync.PENDING)
    sync_error = models.TextField(blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=50)
    target = models.CharField(max_length=300)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def log(user, action, target, **details):
    AuditLog.objects.create(user=user if user and user.is_authenticated else None,
                            action=action, target=str(target)[:300], details=details)
