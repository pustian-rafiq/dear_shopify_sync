"""HTTP endpoints for local/manual cost-sync and Celery testing."""

from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from dear_cost_sync.models import CostSyncLock, CostSyncRecord, CostSyncRun
from dear_cost_sync.tasks import (
    daily_cost_sync,
    force_unlock_cost_sync,
    run_cost_sync_manual,
    weekly_cost_sync,
)


def _allowed(request) -> bool:
    """Allow open access in DEBUG; otherwise staff only."""
    if settings.DEBUG:
        return True
    return bool(request.user.is_authenticated and request.user.is_staff)


def _deny():
    return JsonResponse(
        {
            "ok": False,
            "error": "Forbidden. Enable DEBUG or log in as staff.",
        },
        status=403,
    )


def _bool_param(request, name: str, default=None):
    raw = request.GET.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _int_param(request, name: str, default=None):
    raw = request.GET.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _dispatch(task, *, sync: bool, **kwargs):
    """Queue via Celery (.delay) or run in-process (?sync=1)."""
    if sync:
        result = task(**kwargs)
        return {
            "mode": "sync",
            "result": result,
        }
    async_result = task.delay(**kwargs)
    return {
        "mode": "async",
        "task_id": async_result.id,
        "task_name": task.name,
        "message": "Queued to Celery worker. Watch worker logs / Cost Sync Runs.",
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def health(request):
    """GET /dear_cost_sync/health/"""
    if not _allowed(request):
        return _deny()
    lock = CostSyncLock.objects.filter(name="sync").first()
    latest = CostSyncRun.objects.order_by("-created_at").first()
    return JsonResponse(
        {
            "ok": True,
            "app": "dear_cost_sync",
            "debug": settings.DEBUG,
            "time": timezone.now().isoformat(),
            "lock_held": bool(lock and lock.acquired_at),
            "lock": (
                {
                    "acquired_at": lock.acquired_at.isoformat() if lock and lock.acquired_at else None,
                    "pid": lock.pid if lock else None,
                    "host": lock.host if lock else None,
                }
                if lock
                else None
            ),
            "latest_run": (
                {
                    "id": str(latest.id),
                    "run_type": latest.run_type,
                    "status": latest.status,
                    "dry_run": latest.dry_run,
                    "created_at": latest.created_at.isoformat() if latest.created_at else None,
                }
                if latest
                else None
            ),
            "endpoints": {
                "health": "/dear_cost_sync/health/",
                "daily_dry_run": "/dear_cost_sync/run/daily/?dry_run=true",
                "daily_live": "/dear_cost_sync/run/daily/?dry_run=false",
                "single_sku": "/dear_cost_sync/run/daily/?dry_run=true&sku=YOUR_SKU",
                "weekly": "/dear_cost_sync/run/weekly/",
                "manual": "/dear_cost_sync/run/manual/?dry_run=true",
                "unlock": "/dear_cost_sync/unlock/",
                "runs": "/dear_cost_sync/runs/",
                "beat_info": "/dear_cost_sync/beat/",
                "sync_hint": "Add &sync=1 to run in this process instead of Celery queue",
            },
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def run_daily(request):
    """
    GET /dear_cost_sync/run/daily/?dry_run=true&sku=&max_updates=&force_unlock=0&sync=0
    """
    if not _allowed(request):
        return _deny()
    dry_run = _bool_param(request, "dry_run", default=True)
    sku = request.GET.get("sku") or None
    max_updates = _int_param(request, "max_updates", default=None)
    force_unlock = _bool_param(request, "force_unlock", default=False)
    sync = _bool_param(request, "sync", default=False)
    payload = _dispatch(
        daily_cost_sync,
        sync=sync,
        dry_run=dry_run,
        sku=sku,
        max_updates=max_updates,
        force_unlock=force_unlock,
    )
    return JsonResponse({"ok": True, "action": "daily_cost_sync", **payload})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def run_weekly(request):
    """GET /dear_cost_sync/run/weekly/?dry_run=&sku=&max_updates=&sync=0"""
    if not _allowed(request):
        return _deny()
    dry_run = _bool_param(request, "dry_run", default=None)
    sku = request.GET.get("sku") or None
    max_updates = _int_param(request, "max_updates", default=None)
    force_unlock = _bool_param(request, "force_unlock", default=False)
    sync = _bool_param(request, "sync", default=False)
    payload = _dispatch(
        weekly_cost_sync,
        sync=sync,
        dry_run=dry_run,
        sku=sku,
        max_updates=max_updates,
        force_unlock=force_unlock,
    )
    return JsonResponse({"ok": True, "action": "weekly_cost_sync", **payload})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def run_manual(request):
    """GET /dear_cost_sync/run/manual/?dry_run=true&sku=&sync=0"""
    if not _allowed(request):
        return _deny()
    dry_run = _bool_param(request, "dry_run", default=True)
    sku = request.GET.get("sku") or None
    max_updates = _int_param(request, "max_updates", default=None)
    force_unlock = _bool_param(request, "force_unlock", default=False)
    sync = _bool_param(request, "sync", default=False)
    payload = _dispatch(
        run_cost_sync_manual,
        sync=sync,
        dry_run=dry_run,
        sku=sku,
        max_updates=max_updates,
        force_unlock=force_unlock,
    )
    return JsonResponse({"ok": True, "action": "run_cost_sync_manual", **payload})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def unlock(request):
    """GET /dear_cost_sync/unlock/?sync=0"""
    if not _allowed(request):
        return _deny()
    sync = _bool_param(request, "sync", default=False)
    payload = _dispatch(force_unlock_cost_sync, sync=sync)
    return JsonResponse({"ok": True, "action": "force_unlock_cost_sync", **payload})


@csrf_exempt
@require_http_methods(["GET"])
def list_runs(request):
    """GET /dear_cost_sync/runs/?limit=10"""
    if not _allowed(request):
        return _deny()
    limit = min(_int_param(request, "limit", default=10) or 10, 50)
    runs = CostSyncRun.objects.order_by("-created_at")[:limit]
    data = []
    for r in runs:
        data.append(
            {
                "id": str(r.id),
                "run_type": r.run_type,
                "status": r.status,
                "dry_run": r.dry_run,
                "records_retrieved": r.records_retrieved,
                "records_updated": r.records_updated,
                "records_failed": r.records_failed,
                "records_skipped": r.records_skipped,
                "report_path": r.report_path,
                "error_message": r.error_message,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "record_count": CostSyncRecord.objects.filter(run=r).count(),
            }
        )
    return JsonResponse({"ok": True, "count": len(data), "runs": data})


@csrf_exempt
@require_http_methods(["GET"])
def beat_info(request):
    """
    GET /dear_cost_sync/beat/

    Shows configured Beat schedule and how to test celery beat locally.
    """
    if not _allowed(request):
        return _deny()

    schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {}) or {}
    periodic = []
    try:
        from django_celery_beat.models import PeriodicTask

        for t in PeriodicTask.objects.filter(enabled=True).order_by("name")[:50]:
            periodic.append(
                {
                    "name": t.name,
                    "task": t.task,
                    "enabled": t.enabled,
                    "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
                    "total_run_count": t.total_run_count,
                    "crontab": str(t.crontab) if t.crontab_id else None,
                    "interval": str(t.interval) if t.interval_id else None,
                    "timezone": getattr(t, "timezone", None) or settings.CELERY_TIMEZONE,
                }
            )
    except Exception as exc:
        periodic = [{"error": str(exc)}]

    return JsonResponse(
        {
            "ok": True,
            "celery_timezone": settings.CELERY_TIMEZONE,
            "beat_scheduler": getattr(settings, "CELERY_BEAT_SCHEDULER", None),
            "settings_beat_schedule": schedule,
            "enabled_periodic_tasks": periodic,
            "how_to_test_beat": {
                "1": "Start Redis, then: celery -A dear_to_shopify worker -l info",
                "2": "Start beat: celery -A dear_to_shopify beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler",
                "3": "In admin Periodic tasks, edit dear_cost_sync_daily — set crontab to a minute ahead (e.g. now+2 min)",
                "4": "Wait; worker log should show daily_cost_sync; GET /dear_cost_sync/runs/ for new run",
                "5": "Restore production crontab (0 2 * * *) and timezone America/Los_Angeles if required",
                "manual_url_test": "GET /dear_cost_sync/run/daily/?dry_run=true&sku=YOUR_SKU",
                "in_process_no_worker": "GET /dear_cost_sync/run/daily/?dry_run=true&sync=1",
            },
        }
    )
