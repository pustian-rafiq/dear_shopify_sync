# Celery Beat & URL Testing (Local)

Complete local testing for **Celery worker**, **Celery beat**, and **HTTP URL triggers**.

Base URL (runserver): `http://127.0.0.1:8000`

---

## 1. Start the three processes

From `dear_shopify_sync/` with venv active:

### Terminal A — Django

```bash
python manage.py runserver
```

### Terminal B — Celery worker (required for queued tasks)

```bash
celery -A dear_to_shopify worker -l info
```

Confirm registered tasks include:

- `dear_cost_sync.tasks.daily_cost_sync`
- `dear_cost_sync.tasks.weekly_cost_sync`
- `dear_cost_sync.tasks.run_cost_sync_manual`
- `dear_cost_sync.tasks.force_unlock_cost_sync`

### Terminal C — Celery beat (required for schedule testing)

```bash
celery -A dear_to_shopify beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Redis must be up (`CELERY_URL=redis://localhost:6379/0`).

---

## 2. HTTP endpoints (same codebase)

Open in browser or `curl`. In `DEBUG=True` these are open; in production they require staff login.

| URL | Purpose |
|-----|---------|
| `/dear_cost_sync/health/` | Health, lock, latest run, endpoint list |
| `/dear_cost_sync/beat/` | Beat schedule + PeriodicTask status + how-to |
| `/dear_cost_sync/runs/` | Recent Cost Sync Runs (JSON) |
| `/dear_cost_sync/run/daily/?dry_run=true` | Queue daily dry-run |
| `/dear_cost_sync/run/daily/?dry_run=true&sku=9359825092556` | Single-SKU dry-run |
| `/dear_cost_sync/run/daily/?dry_run=false&max_updates=5` | Limited live |
| `/dear_cost_sync/run/weekly/` | Weekly reconciliation |
| `/dear_cost_sync/run/manual/?dry_run=true` | Manual dry-run |
| `/dear_cost_sync/unlock/` | Force-release sync lock |

### Query flags

| Param | Meaning |
|-------|---------|
| `dry_run=true\|false` | Dry-run vs live |
| `sku=...` | Single-SKU mode |
| `max_updates=N` | Cap live updates |
| `force_unlock=true` | Clear lock before run |
| `sync=1` | Run **in the Django process** (no Celery queue). Good if worker is down. |
| *(omit `sync`)* | Queue with `.delay()` — watch **worker** logs |

### Example curls

```bash
# Health
curl -s http://127.0.0.1:8000/dear_cost_sync/health/ | python -m json.tool

# Beat info
curl -s http://127.0.0.1:8000/dear_cost_sync/beat/ | python -m json.tool

# Queue dry-run (needs worker)
curl -s 'http://127.0.0.1:8000/dear_cost_sync/run/daily/?dry_run=true&sku=9359825092556' | python -m json.tool

# Run in-process (no worker; response waits until sync finishes)
curl -s 'http://127.0.0.1:8000/dear_cost_sync/run/daily/?dry_run=true&sku=9359825092556&sync=1' | python -m json.tool

# List runs
curl -s 'http://127.0.0.1:8000/dear_cost_sync/runs/?limit=5' | python -m json.tool
```

**Async response shape** (queued):

```json
{
  "ok": true,
  "action": "daily_cost_sync",
  "mode": "async",
  "task_id": "...",
  "task_name": "dear_cost_sync.tasks.daily_cost_sync",
  "message": "Queued to Celery worker..."
}
```

Then check worker logs and `/dear_cost_sync/runs/`.

---

## 3. Celery Beat testing (like previous project)

### Step 1 — Confirm schedule exists

```bash
curl -s http://127.0.0.1:8000/dear_cost_sync/beat/ | python -m json.tool
```

Look for:

- `settings_beat_schedule.dear_cost_sync_daily`
- `enabled_periodic_tasks` entry for the daily cost sync (DatabaseScheduler may copy settings into DB)

Also: Admin → **Periodic tasks**.

### Step 2 — Temporary “fire soon” crontab

1. Admin → **Periodic tasks** → open `dear_cost_sync_daily` (or create one if missing).  
2. Task: `dear_cost_sync.tasks.daily_cost_sync`  
3. Enabled: Yes  
4. Crontab: set **minute** to 2–3 minutes ahead of now, **hour** = `*` (every hour) for a quick test.  
5. Optional: set **Timezone** to `America/Los_Angeles` when validating production timing.  
6. For a safe Beat test, keep JobConfiguration `DEAR_COST_DRY_RUN=true`.

Example: if clock is 21:10, set minute=`13`, hour=`*`.

### Step 3 — Watch beat + worker

In **beat** terminal you should see something like:

```text
Scheduler: Sending due task dear_cost_sync_daily (...)
```

In **worker** terminal:

```text
Task dear_cost_sync.tasks.daily_cost_sync[...] received
...
Task ... succeeded
```

### Step 4 — Confirm result

```bash
curl -s 'http://127.0.0.1:8000/dear_cost_sync/runs/?limit=3' | python -m json.tool
```

Or Admin → **Cost Sync Runs**.

Also check Periodic task `last_run_at` / `total_run_count` in admin or `/dear_cost_sync/beat/`.

### Step 5 — Restore production schedule

Set crontab back to daily 02:00:

- Minute: `0`  
- Hour: `2`  
- Day of week / month / month of year: `*`  

Timezone: `America/Los_Angeles` if you need true LA 02:00 (project default `CELERY_TIMEZONE` may be `Australia/Brisbane`).

---

## 4. Recommended local test order

1. `GET /dear_cost_sync/health/` → ok  
2. Fill JobConfiguration secrets  
3. `GET .../run/daily/?dry_run=true&sku=YOUR_SKU` (async) **or** `&sync=1`  
4. `GET .../runs/` → Success / CompletedWithErrors  
5. Beat “fire soon” test (section 3)  
6. Restore crontab  
7. Only then try `dry_run=false` with `max_updates=1`

---

## 5. Troubleshooting

| Issue | Fix |
|-------|-----|
| URL returns queued but no run | Start Celery worker; check Redis |
| Beat sends but worker silent | Worker not connected to same Redis / wrong `-A dear_to_shopify` |
| Periodic task missing | Restart beat once; or create in admin pointing at `dear_cost_sync.tasks.daily_cost_sync` |
| 403 Forbidden | `DEBUG=False` and not logged in as staff |
| Lock error | `GET /dear_cost_sync/unlock/?sync=1` |
| Want response body with full sync result | Use `&sync=1` (blocks until done) |

---

## 6. Production caution

These URLs are convenient for local/UAT. For production:

- Prefer admin actions / Beat only, **or**  
- Keep `DEBUG=False` (staff-only access), **or**  
- Put endpoints behind VPN / auth gateway  

Never leave open live triggers (`dry_run=false`) on a public URL without auth.
