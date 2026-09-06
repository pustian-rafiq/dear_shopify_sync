# DEAR → Shopify Cost Sync — Local End-to-End Testing Guide

Use this checklist to prove the integration works on your machine **before** deploying to DigitalOcean / Docker.

Project root: `dear_shopify_sync/`

Reference sample SKU from requirements: `9359825092556` (Duke Soft White/Silver-9.5, DEAR AverageCost `62.963` → normalised `62.96`).

For **Celery Beat + HTTP URL testing**, see also [`CELERY_BEAT_URL_TESTING.md`](CELERY_BEAT_URL_TESTING.md).

---

## 0. What you are proving

| Stage | Goal | Shopify writes? |
|-------|------|-----------------|
| A. Infra | App boots, DB migrates, Redis/Celery OK | No |
| B. Config | Secrets + JobConfiguration loaded | No |
| C. Single-SKU dry-run | DEAR + Shopify match/compare for one SKU | No |
| D. Full dry-run | Full catalogue reconciliation | No |
| E. Limited live | Real cost update, capped | **Yes** (capped) |
| F. Full live (optional) | Production-like run | **Yes** |
| G. Weekly + schedule | Reconciliation mode + Beat | Depends on mode |
| H. Deploy readiness | Go-live checklist | — |

**Do not start Stage E until Stages C and D look correct.**

---

## 1. Prerequisites

### Software

- Python 3.10+ (3.12 OK with current `requirements.txt`)
- PostgreSQL running on `localhost:5432`
- Redis running on `localhost:6379`
- DEAR (Cin7) API credentials
- Shopify Admin API token with permission to **read and write inventory item cost**
- A known SKU that exists in **both** DEAR (Active) and Shopify

### Terminals you will need (local)

Open **3 terminals** in `dear_shopify_sync/`:

1. Django runserver  
2. Celery worker  
3. Commands / shell (optional 4th: Celery beat)

---

## 2. Stage A — Local infra bootstrap

```bash
cd dear_shopify_sync

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

### `.env` (minimum)

Confirm these exist (do not commit `.env`):

```env
DEBUG=True
DB_HOST=localhost
DB_NAME=dear_shopify_sync
DB_USER=postgres
DB_PASSWORD=your_password
DB_PORT=5432
SECRET_KEY=any-long-random-string
ENVIRONMENT=dev
PROJECT_TITLE=Dear Cost Sync
PROJECT_VERSION=v1.0
CELERY_URL=redis://localhost:6379/0
```

### Create database (once)

```bash
psql -h localhost -U postgres -c "CREATE DATABASE dear_shopify_sync;"
```

### Migrate + superuser

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py check
```

Expected: `System check identified no issues`.

### Start services

**Terminal 1 — Django**

```bash
source venv/bin/activate
python manage.py runserver
```

Open: http://127.0.0.1:8000/admin/

**Terminal 2 — Celery worker (required for admin actions / `.delay()`)**

```bash
source venv/bin/activate
celery -A dear_to_shopify worker -l info
```

Expected: worker starts and shows registered tasks including:

- `dear_cost_sync.tasks.daily_cost_sync`
- `dear_cost_sync.tasks.weekly_cost_sync`
- `dear_cost_sync.tasks.run_cost_sync_manual`

**Optional Terminal 3 — Celery beat** (only needed to test the schedule)

```bash
celery -A dear_to_shopify beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

### Pass criteria (Stage A)

- [ ] Admin loads  
- [ ] Worker is running  
- [ ] No import / migration errors  

---

## 3. Stage B — JobConfiguration

Admin → **Job configurations**.

### Required secrets (must be non-empty)

| config_name | Example / note |
|-------------|----------------|
| `DEAR_ACCOUNT_ID` | Cin7 account id |
| `DEAR_APPLICATION_KEY` | Cin7 application key |
| `SHOPIFY_STORE_DOMAIN` | `your-store.myshopify.com` (no `https://`) |
| `SHOPIFY_ACCESS_TOKEN` | `shpat_…` |

### Keep these for first tests

| config_name | Value |
|-------------|--------|
| `DEAR_COST_DRY_RUN` | `true` |
| `DEAR_COST_MAX_UPDATES` | `0` (unlimited when you go live later) |
| `DEAR_COST_CURRENCY` | `USD` |
| `DEAR_COST_SHOPIFY_API_VERSION` | `2026-07` |
| `DEAR_COST_EMAIL_ENABLED` | `false` (enable later if needed) |
| `DEAR_COST_WEEKLY_MODE` | `reconciliation_only` |

### Verify config is readable

```bash
python manage.py shell -c "
from job_config.models import JobConfiguration
for k in ['DEAR_ACCOUNT_ID','DEAR_APPLICATION_KEY','SHOPIFY_STORE_DOMAIN','SHOPIFY_ACCESS_TOKEN','DEAR_COST_DRY_RUN']:
    v = JobConfiguration.objects.get(config_name=k).config_value
    print(k, 'OK' if (v or '').strip() else 'MISSING', '(len=%s)' % len(v or ''))
"
```

### Pass criteria (Stage B)

- [ ] Four secrets are set  
- [ ] `DEAR_COST_DRY_RUN` is `true`  

---

## 4. Stage C — Single-SKU dry-run (safest E2E)

Pick a SKU that exists in DEAR (Active) and Shopify. Example from docs: `9359825092556`.

### Option 1 — Django shell (recommended)

```bash
python manage.py shell -c "
from dear_cost_sync.tasks import daily_cost_sync
# .delay() needs Celery worker; use () for sync in this process instead:
result = daily_cost_sync(dry_run=True, sku='9359825092556')
print(result)
"
```

Notes:

- Calling `daily_cost_sync(...)` **without** `.delay()` runs in the current process (good for local debugging; watch the terminal).  
- Calling `daily_cost_sync.delay(...)` queues to the **Celery worker** (production-like). Prefer this once worker logs look healthy.

### Option 2 — Celery queue

```bash
python manage.py shell -c "
from dear_cost_sync.tasks import daily_cost_sync
daily_cost_sync.delay(dry_run=True, sku='9359825092556')
print('queued')
"
```

Watch **Terminal 2** for progress and the final summary.

### What to inspect after the run

1. Admin → **Cost Sync Runs**  
   - `run_type` = daily (or manual)  
   - `dry_run` = True  
   - `status` = Success or CompletedWithErrors  
   - `report_path` filled  

2. Admin → **Cost Sync Records** (filter by SKU)  
   - `normalised_dear_cost` e.g. `62.96` if DEAR had `62.963`  
   - `action` / `result`: `UNCHANGED`, `DRY_RUN`, or `SKIPPED` with a clear `error_code`  
   - Never `SUCCESS` in dry-run (SUCCESS only after live update)  

3. Filesystem  

```bash
ls -lt reports/dear_cost_sync/ | head
```

Open the latest CSV; confirm the SKU row.

### Expected outcomes for one SKU

| Situation | Expected `result` / `error_code` |
|-----------|----------------------------------|
| Costs already match | `UNCHANGED` |
| Costs differ | `DRY_RUN` (would update) |
| SKU not in Shopify | `SKIPPED` / `NO_SHOPIFY_MATCH` |
| Multiple Shopify variants | `SKIPPED` / `AMBIGUOUS_MATCH` |
| Bad DEAR cost | `SKIPPED` / `INVALID_COST` |
| Auth failure | Run `Failed`; fix token / DEAR keys |

### Pass criteria (Stage C)

- [ ] Run completes without lock/config crash  
- [ ] One audit row for the SKU (or clear skip reason)  
- [ ] CSV written  
- [ ] Shopify cost **unchanged** in Admin (Inventory item cost)  

---

## 5. Stage D — Full catalogue dry-run

```bash
python manage.py shell -c "
from dear_cost_sync.tasks import daily_cost_sync
result = daily_cost_sync(dry_run=True)
print(result)
"
```

Or Admin → Cost Sync Runs → select any row → action **Run daily cost sync (dry-run)**.

### Review counters

On the run detail, check `counters_json` / note summary for:

- DEAR products retrieved  
- Active products  
- Missing SKU / no match / ambiguous  
- Costs unchanged vs costs changed  
- Failed updates / API errors  
- Runtime  

### Pass criteria (Stage D)

- [ ] Run finishes (may take several minutes)  
- [ ] Counts look plausible vs store size  
- [ ] No unexpected mass `Failed` / auth errors  
- [ ] CSV size / row count looks reasonable  
- [ ] Still no Shopify cost changes  

---

## 6. Stage E — Limited live update

Only after dry-run shows `DRY_RUN` rows you agree with.

### Safety settings

In JobConfiguration:

| config_name | Value |
|-------------|--------|
| `DEAR_COST_DRY_RUN` | `false` **or** leave `true` and pass `dry_run=False` in the task call |
| `DEAR_COST_MAX_UPDATES` | `5` (or `1` / `10`) for first live test |

### Single-SKU live

```bash
python manage.py shell -c "
from dear_cost_sync.tasks import daily_cost_sync
result = daily_cost_sync(dry_run=False, sku='YOUR_SKU', max_updates=1)
print(result)
"
```

### Verify in Shopify

1. Admin → Products → variant → Inventory item **cost**  
2. Expect new cost = `normalised_dear_cost` from the sync record  
3. Sync record `result` = `SUCCESS`  
4. Re-run same SKU dry-run or live → expect `UNCHANGED` (idempotent)

### Pass criteria (Stage E)

- [ ] Shopify cost updated for the test SKU only (within max_updates)  
- [ ] Audit shows `SUCCESS`  
- [ ] Second run is `UNCHANGED`  
- [ ] No unrelated fields changed (price, title, qty)  

---

## 7. Stage F — Broader live (optional pre-prod)

```bash
# Raise or clear cap
# JobConfiguration: DEAR_COST_MAX_UPDATES=0  (unlimited)
# JobConfiguration: DEAR_COST_DRY_RUN=false

python manage.py shell -c "
from dear_cost_sync.tasks import daily_cost_sync
print(daily_cost_sync(dry_run=False))
"
```

Or Admin action **Run daily cost sync (LIVE)**.

### Pass criteria (Stage F)

- [ ] Successful updates ≈ dry-run “costs changed” (minus skips)  
- [ ] Failed rows have readable `error_code` / message  
- [ ] Lock released (`Cost Sync Locks` has empty `acquired_at`)  

If a job dies mid-run and a later job fails with lock held:

```bash
python manage.py shell -c "
from dear_cost_sync.tasks import force_unlock_cost_sync
print(force_unlock_cost_sync())
"
```

---

## 8. Stage G — Weekly + schedule

### Weekly reconciliation (report only)

With `DEAR_COST_WEEKLY_MODE=reconciliation_only`:

```bash
python manage.py shell -c "
from dear_cost_sync.tasks import weekly_cost_sync
print(weekly_cost_sync())
"
```

Expect: forced dry-run (no Shopify writes even if daily is live).

### Beat schedule (02:00)

1. Start celery-beat (Terminal 3).  
2. Admin → **Periodic tasks** → `dear_cost_sync_daily`.  
3. Set **Timezone** to `America/Los_Angeles` if you need true LA 02:00 (project `CELERY_TIMEZONE` may be `Australia/Brisbane`).  
4. For a quick schedule test, temporarily set crontab to a few minutes ahead, wait, confirm a new Cost Sync Run appears, then restore production schedule.

### Pass criteria (Stage G)

- [ ] Weekly run creates a run with weekly type / dry-run when in reconciliation_only  
- [ ] Beat fires the daily task when due  

---

## 9. Stage H — Email (optional)

1. Set SMTP JobConfiguration keys (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_TO_USER`).  
2. Set `DEAR_COST_EMAIL_ENABLED=true`.  
3. Run a dry-run; confirm email arrives with summary (+ CSV if attached).  
4. Confirm a deliberate SMTP failure does **not** mark the sync as Failed solely due to email.

---

## 10. Acceptance checklist (before deploy)

Copy and tick:

- [ ] Stage A–D passed  
- [ ] Stage E passed on at least one real SKU  
- [ ] Idempotent re-run verified (`UNCHANGED`)  
- [ ] Ambiguous / missing SKU behaviour reviewed (no silent wrong matches)  
- [ ] Dry-run default understood; live only when intended  
- [ ] `DEAR_COST_MAX_UPDATES` set to a safe value for first production day (or `0` if approved)  
- [ ] Beat timezone confirmed for 02:00 America/Los_Angeles  
- [ ] Production `.env` has `DEBUG=False`, strong `SECRET_KEY`, production DB/Redis  
- [ ] Production JobConfiguration secrets set (never commit them)  
- [ ] Celery worker + beat will run in production (Docker Compose services `celery` / `celery-beat`)  
- [ ] Rollback plan: set `DEAR_COST_DRY_RUN=true` or disable Periodic Task  

---

## 11. Deploy notes (after local pass)

### Docker Compose (production-like)

```bash
# Ensure .env is production values
docker compose build
docker compose up -d
docker compose logs -f dear_to_shopify celery celery-beat
```

Services:

- `dear_to_shopify` — Gunicorn app  
- `celery` — `celery -A dear_to_shopify worker`  
- `celery-beat` — Beat + DatabaseScheduler  
- `redis` — broker  

### First day in production

1. Keep `DEAR_COST_DRY_RUN=true` for one scheduled run **or** run a manual dry-run on the server.  
2. Review Cost Sync Runs / CSV.  
3. Switch to live with a low `DEAR_COST_MAX_UPDATES`, then raise to `0`.  
4. Monitor worker logs and failed records.

### Emergency stop

- Admin → Periodic tasks → disable `dear_cost_sync_daily`  
- Or set `DEAR_COST_DRY_RUN=true`  
- Or stop celery worker / beat containers  

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Admin action does nothing | Celery worker not running | Start worker; check Redis |
| `Missing required configuration` | Empty JobConfiguration secrets | Fill four required keys |
| `database does not exist` | Postgres DB missing | `CREATE DATABASE dear_shopify_sync` |
| Lock error | Previous run crashed | Force unlock action / task |
| Shopify 401/403 | Bad token or missing scopes | Regenerate Admin token with cost permissions |
| DEAR auth error | Bad account id / app key | Fix DEAR_* configs |
| Currency skips | Shopify currency ≠ `DEAR_COST_CURRENCY` | Align currency or expected value |
| Beat at wrong wall-clock time | TZ mismatch | Set PeriodicTask timezone to `America/Los_Angeles` |

---

## 13. Quick command cheat sheet

```bash
# Sync dry-run one SKU (in-process)
python manage.py shell -c "from dear_cost_sync.tasks import daily_cost_sync; print(daily_cost_sync(dry_run=True, sku='SKU'))"

# Queue dry-run (needs worker)
python manage.py shell -c "from dear_cost_sync.tasks import daily_cost_sync; daily_cost_sync.delay(dry_run=True)"

# Limited live
python manage.py shell -c "from dear_cost_sync.tasks import daily_cost_sync; print(daily_cost_sync(dry_run=False, max_updates=5))"

# Weekly report-only
python manage.py shell -c "from dear_cost_sync.tasks import weekly_cost_sync; print(weekly_cost_sync())"

# Unlock
python manage.py shell -c "from dear_cost_sync.tasks import force_unlock_cost_sync; print(force_unlock_cost_sync())"
```

---

*Document version: matches `dear_cost_sync` Django app + Celery Beat scheduling. Keep dry-run until Stages C–D pass.*
