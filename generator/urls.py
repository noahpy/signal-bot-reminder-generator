from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from reminders import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="reminders/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.index, name="index"),
    path("groups/<int:pk>/", views.mapping_detail, name="mapping_detail"),
    path("groups/<int:mapping_pk>/new/", views.reminder_new, name="reminder_new"),
    path("reminders/<int:pk>/", views.reminder_edit, name="reminder_edit"),
    path("reminders/<int:pk>/copy/", views.reminder_copy, name="reminder_copy"),
    path("reminders/<int:pk>/delete/", views.reminder_delete, name="reminder_delete"),
    path("reminders/<int:pk>/toggle/", views.reminder_toggle, name="reminder_toggle"),
    path("reminders/<int:pk>/run/", views.reminder_run, name="reminder_run"),
    path("reminders/<int:pk>/logs/", views.reminder_logs, name="reminder_logs"),
    path("manage/", views.admin_home, name="admin_home"),
    path("manage/mappings/new/", views.mapping_edit, name="mapping_new"),
    path("manage/mappings/<int:pk>/", views.mapping_edit, name="mapping_edit"),
    path("manage/mappings/<int:pk>/delete/", views.mapping_delete, name="mapping_delete"),
    path("manage/mappings/<int:pk>/members/", views.mapping_members, name="mapping_members"),
    path("manage/resync/", views.resync_all, name="resync_all"),
    path("manage/sync-groups/", views.sync_signal_groups, name="sync_signal_groups"),
    path("django-admin/", admin.site.urls),
]
