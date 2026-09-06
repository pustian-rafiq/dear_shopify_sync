"""Celery tasks for DEAR → Shopify cost sync."""

from celery import shared_task

from dear_cost_sync.task_mixins import CostSyncTaskMixin


@shared_task
def daily_cost_sync(
    dry_run=None, sku=None, max_updates=None, force_unlock=False
):
    """
    Daily DEAR AverageCost → Shopify inventory item cost sync.

    dry_run: None uses JobConfiguration DEAR_COST_DRY_RUN (default true).
             Pass False for live updates, True to force dry-run.
    sku: optional single-SKU test mode.
    max_updates: optional cap on live updates this run.
    force_unlock: clear a stale CostSyncLock before acquiring.
    """
    mixin = CostSyncTaskMixin()
    result = mixin.execute_sync(
        run_type="daily",
        dry_run=dry_run,
        sku=sku,
        max_updates=max_updates,
        force_unlock=force_unlock,
        weekly=False,
        note="Daily DEAR cost sync",
    )
    print("Daily cost sync finished:", result.get("status"), result.get("run_id"))
    return result


@shared_task
def weekly_cost_sync(
    dry_run=None, sku=None, max_updates=None, force_unlock=False
):
    """
    Weekly reconciliation. Mode from DEAR_COST_WEEKLY_MODE:
      reconciliation_only  -> force dry-run
      reconcile_and_correct -> honour dry_run / live flags
    Enable this task in django-celery-beat admin when needed.
    """
    mixin = CostSyncTaskMixin()
    result = mixin.execute_sync(
        run_type="weekly",
        dry_run=dry_run,
        sku=sku,
        max_updates=max_updates,
        force_unlock=force_unlock,
        weekly=True,
        note="Weekly DEAR cost reconciliation",
    )
    print("Weekly cost sync finished:", result.get("status"), result.get("run_id"))
    return result


@shared_task
def run_cost_sync_manual(
    dry_run=True, sku=None, max_updates=None, force_unlock=False
):
    """Admin / manual trigger (defaults to dry-run for safety)."""
    mixin = CostSyncTaskMixin()
    result = mixin.execute_sync(
        run_type="manual",
        dry_run=dry_run,
        sku=sku,
        max_updates=max_updates,
        force_unlock=force_unlock,
        weekly=False,
        note="Manual DEAR cost sync",
    )
    print("Manual cost sync finished:", result.get("status"), result.get("run_id"))
    return result


@shared_task
def force_unlock_cost_sync():
    """Clear the cost-sync lock (admin recovery)."""
    mixin = CostSyncTaskMixin()
    held = mixin.force_unlock()
    print(f"Force unlock: was_held={held}")
    return {"was_held": held}
