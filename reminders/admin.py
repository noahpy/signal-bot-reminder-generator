from django.contrib import admin

from .models import AuditLog, GroupMapping, LdapProfile, Reminder

admin.site.register(GroupMapping)
admin.site.register(LdapProfile)


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ("title", "mapping", "enabled", "sync_status", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "target")
