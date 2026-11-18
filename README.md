# signal-bot-reminder-generator

Self-service web app: residents log in with their Schollheim LDAP account and create
reminder jobs that [signal-bot](https://github.com/noahpy/signal-bot-manager) posts into
their floor's Signal group (with @mentions). Replaces hand-written scripts like
`putztask_reminder.py` with several declarative reminders.

## How it works

- **Group mappings** (admin): LDAP group (e.g. `cn=H2F4,ou=groups2,…`) ↔ Signal group.
  Members of the LDAP group can manage that Signal group's reminders.
- **Reminders** are declarative JSON specs (no code): schedule (weekly / monthly /
  every N days / list of dates / once), people (picked from the Signal group's member
  list, stored by UUID), rotation or "everyone", lead days, send time, message template.
- On save, the spec is pushed to signal-bot's API (`PUT /api/v1/reminders/<uuid>/`), which
  creates a job running `scripts/reminder_runner.py`. The generator is the source of truth;
  *Manage → Re-push all reminders* re-syncs everything and removes orphaned jobs.

## Configuration (env, see `generator/settings.py`)

| Variable | Meaning |
|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DB_PATH`, `STATIC_ROOT` | Django basics |
| `HTTPS` | `1` when served through nginx with TLS (trust `X-Forwarded-Proto`, secure cookies) |
| `LDAP_URI`, `LDAP_START_TLS` | e.g. `ldap://ldap.schollheim.net:389` |
| `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD` | read-only service account `cn=signal-reminder,ou=services,dc=schollheim,dc=net` |
| `LDAP_BASE_DN`, `LDAP_USER_BASE`, `LDAP_USER_ATTR` | users are `cn=<login>,ou=users,…` |
| `LDAP_GROUP_BASES` | `;`-separated, default `ou=groups;ou=roles;ou=groups2` |
| `LDAP_ADMIN_GROUPS` | `;`-separated group DNs whose members get the admin dashboard |
| `SIGNAL_BOT_API_URL`, `SIGNAL_BOT_API_TOKEN` | signal-bot API (token = signal-bot's `REMINDER_API_TOKEN`) |

Local Django accounts (`createsuperuser`) also work and are tried first.

## Importing the old putztask plan

```bash
uv run python manage.py import_putztasks /path/to/putztasks.json --mapping <id>          # dry run
uv run python manage.py import_putztasks /path/to/putztasks.json --mapping <id> --apply
```

## Deployment (signal-bot.schollheim.net)

- Code `/opt/reminder-generator` (user `reminders`), env `/etc/reminder-generator.env`,
  DB `/var/lib/reminder-generator/db.sqlite3`.
- `reminder-generator.service` (gunicorn on 127.0.0.1:8100); nginx serves it at `https://signal-bot.schollheim.net` with the Schollheim wildcard certificate (expires 2027-01-31, renew by hand; old http/8080 links redirect)
  and on port 80 for `reminders.schollheim.net` (once DNS exists). Intranet only, no TLS yet.
- Update: `rsync -az --delete --exclude .venv --exclude db.sqlite3 --exclude .git ./ signal-bot.schollheim.net:/opt/reminder-generator/`,
  then on the VM: `sudo chown -R reminders: /opt/reminder-generator && sudo -u reminders bash -lc 'cd /opt/reminder-generator && set -a && . /etc/reminder-generator.env && set +a && ~/.local/bin/uv sync --frozen && ~/.local/bin/uv run python manage.py migrate && ~/.local/bin/uv run python manage.py collectstatic --noinput' && sudo systemctl restart reminder-generator`

## Tests

`uv run python manage.py test reminders`
