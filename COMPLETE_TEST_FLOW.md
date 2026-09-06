# Complete Test Flow — Settings Beat → Every Function

End-to-end path from **Celery Beat schedule in settings** through **every major function** in `dear_cost_sync`, with what to check at each step.

```text
settings.CELERY_BEAT_SCHEDULE
        │
        ▼
Celery Beat  ──queues──►  Celery Worker
        │                       │
        │                       ▼
        │              daily_cost_sync()   [tasks.py]
        │                       │
        │                       ▼
        │              CostSyncTaskMixin.execute_sync()
        │                       │
        │         ┌─────────────┼─────────────────────────────┐
        │         ▼             ▼                             ▼
        │   load_config   acquire_lock                  create_run
        │         │             │                             │
        │         ▼             │                             ▼
        │   build_sync_options  │                      build_clients
        │         │             │                             │
        │         └──────┬──────┘                             │
        │                ▼                                    ▼
        │         SyncService.run()  ◄──── DearClient + ShopifyClient
        │                │
        │                ▼
        │         persist_records → write_csv_report → finalise_run
        │                │
        │                ▼
        │         send_report_email (optional) → release_lock
        ▼
   CostSyncRun / CostSyncRecord / CSV / JSON URL response
```

---

## Before you start (once)

```bash
cd dear_shopify_sync
source venv/bin/activate

# Terminal A
python manage.py runserver

# Terminal B
celery -A dear_to_shopify worker -l info

# Terminal C (for Beat path only)
celery -A dear_to_shopify beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Confirm JobConfiguration has:

- `DEAR_ACCOUNT_ID`, `DEAR_APPLICATION_KEY`, `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_ACCESS_TOKEN`
- `DEAR_COST_DRY_RUN=true` for first full pass

Quick entry points:

| Trigger                   | How                                                   |
| ------------------------- | ----------------------------------------------------- |
| Beat (production path)    | Wait for schedule / temporary crontab                 |
| URL (async)               | `GET /dear_cost_sync/run/daily/?dry_run=true&sku=SKU` |
| URL (sync, see full JSON) | same + `&sync=1`                                      |
| Shell                     | `daily_cost_sync(dry_run=True, sku='SKU')`            |

---

## STEP 0 — Settings schedule definition

**File:** `dear_to_shopify/settings.py`

```python
CELERY_BEAT_SCHEDULE = {
    'dear_cost_sync_daily': {
        'task': 'dear_cost_sync.tasks.daily_cost_sync',
        'schedule': crontab(minute=0, hour=2),
    },
}
```

| Check               | How                                                                                           |
| ------------------- | --------------------------------------------------------------------------------------------- |
| Schedule registered | `GET /dear_cost_sync/beat/` → `settings_beat_schedule`                                        |
| Timezone            | `celery_timezone` in same response (`Australia/Brisbane` unless you override PeriodicTask TZ) |
| DB PeriodicTask     | Admin → Periodic tasks → `dear_cost_sync_daily`                                               |

**Pass:** Beat info JSON shows `dear_cost_sync.tasks.daily_cost_sync`.

---

## STEP 1 — Celery Beat sends the task

**Process:** `celery -A dear_to_shopify beat ...`

Beat reads `DatabaseScheduler` + settings schedule and publishes the task to Redis.

| Check         | How                                                     |
| ------------- | ------------------------------------------------------- |
| Beat is alive | Terminal C logs “beat: Starting…”                       |
| Due task sent | Log: `Scheduler: Sending due task dear_cost_sync_daily` |
| Quick test    | Admin Periodic task: set minute = now+2, wait           |

**Pass:** Beat log shows send; Redis receives message (worker will pick it up next).

---

## STEP 2 — Celery Worker receives task

**Process:** `celery -A dear_to_shopify worker -l info`  
**Entry:** `dear_cost_sync.tasks.daily_cost_sync`

```python
@shared_task
def daily_cost_sync(dry_run=None, sku=None, max_updates=None, force_unlock=False):
    mixin = CostSyncTaskMixin()
    result = mixin.execute_sync(run_type="daily", ...)
    return result
```

| Check             | How                                                         |
| ----------------- | ----------------------------------------------------------- |
| Task registered   | Worker startup lists `dear_cost_sync.tasks.daily_cost_sync` |
| Task received     | `Task ...daily_cost_sync[...] received`                     |
| Alternate trigger | URL without `sync=1` → response has `task_id`               |

Same entry for:

- `weekly_cost_sync` → `execute_sync(..., weekly=True)`
- `run_cost_sync_manual` → `run_type="manual"`
- URL views → `task.delay(...)` or `task(...)` if `sync=1`

**Pass:** Worker shows `received` then later `succeeded` (or exception traceback).

---

## STEP 3 — `execute_sync` starts

**File:** `dear_cost_sync/task_mixins.py` → `CostSyncTaskMixin.execute_sync`

### 3.1 `load_config()`

Reads `JobConfiguration` (fallback `.env`).

Calls: `get_config_value`, `_as_bool`, `_as_int`

| Check          | How                                                      |
| -------------- | -------------------------------------------------------- |
| Missing secret | Run without secrets → `ConfigurationError` / Failed run  |
| Values loaded  | Worker prints `DEAR cost sync starting (daily, DRY-RUN)` |

**Pass:** No config error; mode label matches `DEAR_COST_DRY_RUN`.

### 3.2 `build_sync_options()`

Builds `SyncOptions` (dry_run, tolerance, currency, single_sku, …).  
If weekly: also `effective_weekly_options()` in `services/reconciliation.py`.

| Check                 | How                                                                           |
| --------------------- | ----------------------------------------------------------------------------- |
| Weekly forces dry-run | `DEAR_COST_WEEKLY_MODE=reconciliation_only` + weekly URL → run `dry_run=True` |
| SKU mode              | Pass `sku=` → only that SKU processed                                         |

**Pass:** Run row shows expected `dry_run` / behaviour.

### 3.3 `acquire_lock()`

Writes `CostSyncLock` name=`sync`.

| Check                | How                                                    |
| -------------------- | ------------------------------------------------------ |
| Lock held during run | Mid-run: `/dear_cost_sync/health/` → `lock_held: true` |
| Double run blocked   | Start second sync while first runs → `LockError`       |
| Unlock               | `/dear_cost_sync/unlock/?sync=1`                       |

**Pass:** Overlap rejected; unlock clears lock.

### 3.4 `create_run()`

Inserts `CostSyncRun` status=`Processing`.

| Check       | How                                            |
| ----------- | ---------------------------------------------- |
| Row appears | Admin Cost Sync Runs / `/dear_cost_sync/runs/` |

**Pass:** New run with `status=Processing` then final status.

---

## STEP 4 — Clients built

**File:** `task_mixins.build_clients()`

- `DearClient(...)` → `services/dear_client.py`
- `ShopifyClient(...)` → `services/shopify_client.py`

| Check             | How                           |
| ----------------- | ----------------------------- |
| Bad DEAR keys     | Auth error → run Failed       |
| Bad Shopify token | 401/403 → Failed / api_errors |

**Pass:** Clients construct; first API call succeeds or fails clearly.

---

## STEP 5 — `SyncService.run()` (core business logic)

**File:** `services/sync_service.py`

### 5.1 DEAR fetch — `DearClient.fetch_all_products()` / `iter_products()`

Functions involved:

- `_request` (GET Product, retries, rate limit)
- `_extract_products`, `_extract_total`
- Pagination guards (empty page, duplicate page, Total)

| Check            | How                                                          |
| ---------------- | ------------------------------------------------------------ |
| Pagination works | Worker logs `DEAR page N: ...`                               |
| Counters         | Run `records_retrieved` / counters `dear_products_retrieved` |

**Pass:** Retrieved count > 0 (or empty catalogue with retrieved=0).

### 5.2 Filter + normalise — `normalise_cost()`

**File:** `services/decimal_utils.py`

- Active only (unless include inactive)
- Missing SKU → `MISSING_SKU`
- Invalid cost → `INVALID_COST`
- Example: `62.963` → `62.96` (`ROUND_HALF_UP`)

| Check    | How                                                             |
| -------- | --------------------------------------------------------------- |
| Rounding | Record `normalised_dear_cost` for sample SKU                    |
| Skips    | Records with `error_code` MISSING_SKU / INVALID_COST / INACTIVE |

**Pass:** Known SKU shows correct normalised cost.

### 5.3 Shopify lookup — `ShopifyClient.lookup_variants_by_skus()`

Functions:

- `escape_sku_for_search`
- `_paginate_variants` (GraphQL + pageInfo)
- Exact SKU filter client-side

| Check      | How                                                           |
| ---------- | ------------------------------------------------------------- |
| Match      | Record has `shopify_variant_id` + `shopify_inventory_item_id` |
| No match   | `NO_SHOPIFY_MATCH`                                            |
| Duplicates | `AMBIGUOUS_MATCH`                                             |

**Pass:** Exactly one of match / skip codes; never silent guess.

### 5.4 Compare — `costs_differ()`

| Check     | How                                     |
| --------- | --------------------------------------- |
| Same cost | `result=UNCHANGED`                      |
| Different | dry-run → `DRY_RUN`; live → update path |

### 5.5 Update (live only) — `ShopifyClient.update_inventory_item_cost()`

Mutation `inventoryItemUpdate` with `input.cost` string; handles `userErrors`.

| Check        | How                                                  |
| ------------ | ---------------------------------------------------- |
| Dry-run      | No Shopify change; `DRY_RUN`                         |
| Live success | Shopify cost updated; `SUCCESS`                      |
| Cap          | `max_updates=1` → further rows `MAX_UPDATES_REACHED` |
| userErrors   | `FAILED` + `SHOPIFY_USER_ERROR`                      |

**Pass:** Idempotent second run → `UNCHANGED`.

---

## STEP 6 — Persist audit

### 6.1 `persist_records()`

Bulk-creates `CostSyncRecord` rows linked to the run.

| Check | Admin Cost Sync Records / filter by SKU |

### 6.2 `write_csv_report()` — `services/reporting.py`

Writes under `DEAR_COST_REPORT_DIR` (default `reports/dear_cost_sync/`).

| Check | `ls -lt reports/dear_cost_sync/` ; open CSV |

### 6.3 `build_summary()` / `determine_status()` / `finalise_run()`

Status:

- `Success` if no failed updates / api errors
- `CompletedWithErrors` if failures
- `Failed` on hard exception

| Check | Run `status`, `note` (summary text), `counters_json`, `report_path` |

**Pass:** Run completed; CSV path set; counters match records.

---

## STEP 7 — Email (optional)

If `DEAR_COST_EMAIL_ENABLED=true`:

- `set_email_configuration()` → JobConfiguration EMAIL\_\*
- `send_report_email()` → SMTP

| Check | Inbox; email failure must not fail sync alone |

**Pass:** Email sent or logged as non-fatal.

---

## STEP 8 — `release_lock()` (always in `finally`)

| Check | `/dear_cost_sync/health/` → `lock_held: false` |

**Pass:** Lock clear after success or failure.

---

## STEP 9 — Return / observe result

| Trigger                      | Where result appears                                     |
| ---------------------------- | -------------------------------------------------------- |
| Worker + Beat / `.delay()`   | Worker log + `/dear_cost_sync/runs/` + Admin             |
| URL `?sync=1`                | JSON body includes `result.run_id`, `status`, `counters` |
| Shell `daily_cost_sync(...)` | Printed dict                                             |

Example success shape:

```json
{
  "run_id": "...",
  "status": "Success",
  "dry_run": true,
  "counters": {
    "dear_products_retrieved": 1234,
    "active_products": 1200,
    "shopify_matches": 1100,
    "costs_unchanged": 1000,
    "costs_changed": 50,
    "successful_updates": 0,
    "failed_updates": 0,
    "skipped_records": 100,
    "runtime_seconds": 45.2
  },
  "report_path": "reports/dear_cost_sync/cost_sync_daily_run....csv"
}
```

---

## Recommended full test sequence (tick as you go)

### A. Settings → Beat → Worker (no DEAR yet)

1. [ ] `/dear_cost_sync/beat/` shows schedule
2. [ ] Worker lists `daily_cost_sync`
3. [ ] Temporary PeriodicTask crontab → Beat “Sending due task”
4. [ ] Worker “received” (may fail later on empty secrets — still proves plumbing)

### B. Config + lock

5. [ ] Secrets filled
6. [ ] Health shows lock free
7. [ ] Force unlock works

### C. Single-SKU dry-run (all functions through update skipped)

8. [ ] Trigger:  
       `GET /dear_cost_sync/run/daily/?dry_run=true&sku=YOUR_SKU&sync=1`
9. [ ] `load_config` OK (no config error)
10. [ ] Lock acquired then released
11. [ ] Run created → finalised
12. [ ] DEAR product loaded / normalised
13. [ ] Shopify match or clear skip code
14. [ ] CSV written
15. [ ] Records in admin

### D. Full dry-run

16. [ ] `/dear_cost_sync/run/daily/?dry_run=true` (or Beat with dry_run config)
17. [ ] Counters look plausible
18. [ ] No Shopify writes

### E. Limited live (update path)

19. [ ] `dry_run=false&sku=YOUR_SKU&max_updates=1&sync=1`
20. [ ] Shopify cost updated
21. [ ] Re-run → `UNCHANGED`

### F. Weekly path

22. [ ] `/dear_cost_sync/run/weekly/?sync=1`
23. [ ] With `reconciliation_only` → forced dry-run

### G. Restore production Beat

24. [ ] Crontab back to `0 2 * * *`
25. [ ] TZ set for LA if required
26. [ ] `DEAR_COST_DRY_RUN` set intentionally for first deploy day

---

## Function checklist (code map)

| Step         | Module              | Function(s)                                                     |
| ------------ | ------------------- | --------------------------------------------------------------- |
| Schedule     | `settings.py`       | `CELERY_BEAT_SCHEDULE`                                          |
| Task entry   | `tasks.py`          | `daily_cost_sync` / `weekly_cost_sync` / `run_cost_sync_manual` |
| HTTP entry   | `views.py`          | `run_daily`, `run_weekly`, `health`, `beat_info`, `list_runs`   |
| Orchestrate  | `task_mixins.py`    | `execute_sync`                                                  |
| Config       | `task_mixins.py`    | `load_config`, `get_config_value`, `build_sync_options`         |
| Weekly mode  | `reconciliation.py` | `effective_weekly_options`                                      |
| Lock         | `task_mixins.py`    | `acquire_lock`, `release_lock`, `force_unlock`                  |
| Run DB       | `task_mixins.py`    | `create_run`, `finalise_run`, `persist_records`                 |
| Clients      | `task_mixins.py`    | `build_clients`                                                 |
| DEAR HTTP    | `dear_client.py`    | `fetch_all_products`, `iter_products`, `_request`               |
| Money        | `decimal_utils.py`  | `normalise_cost`, `costs_differ`, `decimal_to_cost_string`      |
| Sync core    | `sync_service.py`   | `SyncService.run`                                               |
| Shopify HTTP | `shopify_client.py` | `lookup_variants_by_skus`, `update_inventory_item_cost`         |
| Report       | `reporting.py`      | `write_csv_report`, `build_summary`, `build_html_summary`       |
| Email        | `task_mixins.py`    | `set_email_configuration`, `send_report_email`                  |

---

## One-liner “happy path” (dry-run, all steps)

```bash
# 1) Plumbing
curl -s http://127.0.0.1:8000/dear_cost_sync/health/ | python -m json.tool
curl -s http://127.0.0.1:8000/dear_cost_sync/beat/ | python -m json.tool

# 2) Full function chain for one SKU (in-process = wait for JSON result)
curl -s 'http://127.0.0.1:8000/dear_cost_sync/run/daily/?dry_run=true&sku=YOUR_SKU&sync=1' | python -m json.tool

# 3) Confirm persistence
curl -s 'http://127.0.0.1:8000/dear_cost_sync/runs/?limit=1' | python -m json.tool
ls -lt reports/dear_cost_sync/ | head
```

Then prove Beat separately with a temporary crontab (Step 1) while worker is running.

---

_After this flow passes, you are ready to deploy with dry-run first, then limited live, then full live._
