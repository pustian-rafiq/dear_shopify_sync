"""Config loading, locking, persistence, reporting, and email for cost sync."""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from decouple import config
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone as dj_timezone
from job_config.models import JobConfiguration

from dear_cost_sync.models import CostSyncLock, CostSyncRecord, CostSyncRun
from dear_cost_sync.services.dear_client import DearClient
from dear_cost_sync.services.domain import Action, Result, RunCounters, SyncRecord
from dear_cost_sync.services.exceptions import ConfigurationError, LockError
from dear_cost_sync.services.reconciliation import effective_weekly_options
from dear_cost_sync.services.reporting import (
    build_html_summary,
    build_summary,
    write_csv_report,
)
from dear_cost_sync.services.shopify_client import ShopifyClient
from dear_cost_sync.services.sync_service import SyncOptions, SyncService

logger = logging.getLogger(__name__)

DEAR_BASE_URL_DEFAULT = "https://inventory.dearsystems.com/externalapi/v2"
LOCK_NAME = "sync"


@dataclass
class CostSyncConfig:
    dear_account_id: str
    dear_application_key: str
    dear_base_url: str
    shopify_store_domain: str
    shopify_access_token: str
    shopify_api_version: str
    dry_run: bool
    max_updates_per_run: int
    page_size: int
    variant_batch_size: int
    tolerance: str
    currency: str
    email_enabled: bool
    weekly_mode: str
    include_inactive: bool
    report_dir: str
    request_timeout: int
    max_retries: int
    rate_limit_per_minute: int


class CostSyncTaskMixin:
    """Common helpers for cost-sync Celery tasks."""

    def get_config_value(self, name: str, default=None, *, required: bool = False):
        """Prefer JobConfiguration; fall back to .env via decouple."""
        try:
            return JobConfiguration.objects.get(config_name=name).config_value
        except JobConfiguration.DoesNotExist:
            pass
        env_val = config(name, default=None)
        if env_val is not None and env_val != "":
            return env_val
        if required:
            raise ConfigurationError(
                f"Missing required configuration: {name} "
                f"(set JobConfiguration or .env)"
            )
        return default

    def _as_bool(self, value, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _as_int(self, value, default: int = 0) -> int:
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def load_config(self) -> CostSyncConfig:
        dear_account_id = self.get_config_value("DEAR_ACCOUNT_ID", required=True)
        dear_application_key = self.get_config_value(
            "DEAR_APPLICATION_KEY", required=True
        )

        store_domain = self.get_config_value("SHOPIFY_STORE_DOMAIN", default=None)
        access_token = self.get_config_value("SHOPIFY_ACCESS_TOKEN", default=None)
        if not access_token:
            # Reuse existing Shopify token key from BC integration when present.
            access_token = self.get_config_value("SHOPIFY_API_KEY", default=None)
        if not store_domain:
            raise ConfigurationError(
                "Missing SHOPIFY_STORE_DOMAIN (JobConfiguration or .env)"
            )
        if not access_token:
            raise ConfigurationError(
                "Missing SHOPIFY_ACCESS_TOKEN or SHOPIFY_API_KEY "
                "(JobConfiguration or .env)"
            )

        store_domain = str(store_domain).strip()
        store_domain = store_domain.replace("https://", "").replace("http://", "")
        store_domain = store_domain.rstrip("/")

        return CostSyncConfig(
            dear_account_id=str(dear_account_id).strip(),
            dear_application_key=str(dear_application_key).strip(),
            dear_base_url=self.get_config_value(
                "DEAR_BASE_URL", default=DEAR_BASE_URL_DEFAULT
            ),
            shopify_store_domain=store_domain,
            shopify_access_token=str(access_token).strip(),
            shopify_api_version=self.get_config_value(
                "DEAR_COST_SHOPIFY_API_VERSION", default="2026-07"
            ),
            dry_run=self._as_bool(
                self.get_config_value("DEAR_COST_DRY_RUN", default="true"), True
            ),
            max_updates_per_run=self._as_int(
                self.get_config_value("DEAR_COST_MAX_UPDATES", default="0"), 0
            ),
            page_size=self._as_int(
                self.get_config_value("DEAR_COST_PAGE_SIZE", default="1000"), 1000
            ),
            variant_batch_size=self._as_int(
                self.get_config_value("DEAR_COST_VARIANT_BATCH_SIZE", default="50"), 50
            ),
            tolerance=str(
                self.get_config_value("DEAR_COST_TOLERANCE", default="0.00")
            ),
            currency=str(
                self.get_config_value("DEAR_COST_CURRENCY", default="USD")
            ),
            email_enabled=self._as_bool(
                self.get_config_value("DEAR_COST_EMAIL_ENABLED", default="false"), False
            ),
            weekly_mode=str(
                self.get_config_value(
                    "DEAR_COST_WEEKLY_MODE", default="reconciliation_only"
                )
            ),
            include_inactive=self._as_bool(
                self.get_config_value("DEAR_COST_INCLUDE_INACTIVE", default="false"),
                False,
            ),
            report_dir=str(
                self.get_config_value(
                    "DEAR_COST_REPORT_DIR", default="reports/dear_cost_sync"
                )
            ),
            request_timeout=self._as_int(
                self.get_config_value("DEAR_COST_REQUEST_TIMEOUT", default="30"), 30
            ),
            max_retries=self._as_int(
                self.get_config_value("DEAR_COST_MAX_RETRIES", default="5"), 5
            ),
            rate_limit_per_minute=self._as_int(
                self.get_config_value("DEAR_COST_RATE_LIMIT", default="60"), 60
            ),
        )

    # -- locking ----------------------------------------------------------
    def acquire_lock(self, force_unlock: bool = False) -> None:
        with transaction.atomic():
            lock, _ = CostSyncLock.objects.select_for_update().get_or_create(
                name=LOCK_NAME,
                defaults={"acquired_at": None, "pid": None, "host": None},
            )
            if force_unlock and lock.acquired_at is not None:
                logger.warning("Force-releasing cost sync lock held since %s", lock.acquired_at)
                lock.acquired_at = None
                lock.pid = None
                lock.host = None
                lock.save(update_fields=["acquired_at", "pid", "host"])

            if lock.acquired_at is not None:
                raise LockError(
                    f"Cost sync lock is held (pid={lock.pid}, host={lock.host}, "
                    f"acquired_at={lock.acquired_at})"
                )
            lock.acquired_at = dj_timezone.now()
            lock.pid = os.getpid()
            lock.host = socket.gethostname()
            lock.save(update_fields=["acquired_at", "pid", "host"])

    def release_lock(self) -> None:
        with transaction.atomic():
            try:
                lock = CostSyncLock.objects.select_for_update().get(name=LOCK_NAME)
            except CostSyncLock.DoesNotExist:
                return
            lock.acquired_at = None
            lock.pid = None
            lock.host = None
            lock.save(update_fields=["acquired_at", "pid", "host"])

    def force_unlock(self) -> bool:
        with transaction.atomic():
            try:
                lock = CostSyncLock.objects.select_for_update().get(name=LOCK_NAME)
            except CostSyncLock.DoesNotExist:
                return False
            held = lock.acquired_at is not None
            lock.acquired_at = None
            lock.pid = None
            lock.host = None
            lock.save(update_fields=["acquired_at", "pid", "host"])
            return held

    # -- run lifecycle ----------------------------------------------------
    def create_run(self, run_type: str, dry_run: bool, note: str = "") -> CostSyncRun:
        return CostSyncRun.objects.create(
            run_type=run_type,
            status=CostSyncRun.Status.PROCESSING,
            dry_run=dry_run,
            note=note or None,
            started_at=dj_timezone.now(),
        )

    def finalise_run(
        self,
        run: CostSyncRun,
        *,
        status: str,
        counters: RunCounters,
        report_path: Optional[str] = None,
        error_message: Optional[str] = None,
        note: Optional[str] = None,
    ) -> CostSyncRun:
        run.status = status
        run.counters_json = counters.as_dict()
        run.records_retrieved = counters.dear_products_retrieved
        run.records_processed = counters.active_products
        run.records_updated = counters.successful_updates
        run.records_failed = counters.failed_updates
        run.records_skipped = counters.skipped_records
        run.report_path = report_path
        run.error_message = error_message
        if note is not None:
            run.note = note
        run.completed_at = dj_timezone.now()
        run.save()
        return run

    def persist_records(self, run: CostSyncRun, records: list[SyncRecord]) -> None:
        rows = []
        for r in records:
            processed_at = None
            if r.processed_at_utc:
                try:
                    processed_at = datetime.strptime(
                        r.processed_at_utc[:19], "%Y-%m-%dT%H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    processed_at = dj_timezone.now()
            rows.append(
                CostSyncRecord(
                    run=run,
                    dear_product_id=r.dear_product_id,
                    sku=r.sku,
                    dear_name=(r.dear_name or "")[:500] if r.dear_name else None,
                    dear_status=r.dear_status,
                    dear_average_cost=r.dear_average_cost,
                    normalised_dear_cost=r.normalised_dear_cost,
                    shopify_variant_id=r.shopify_variant_id,
                    shopify_inventory_item_id=r.shopify_inventory_item_id,
                    shopify_product_id=r.shopify_product_id,
                    shopify_product_title=(
                        (r.shopify_product_title or "")[:500]
                        if r.shopify_product_title
                        else None
                    ),
                    shopify_product_status=r.shopify_product_status,
                    previous_shopify_cost=r.previous_shopify_cost,
                    new_shopify_cost=r.new_shopify_cost,
                    shopify_currency=r.shopify_currency,
                    action=(
                        r.action.value if isinstance(r.action, Action) else r.action
                    ),
                    result=(
                        r.result.value if isinstance(r.result, Result) else r.result
                    ),
                    error_code=r.error_code,
                    error_message=r.error_message,
                    processed_at=processed_at,
                )
            )
        if rows:
            CostSyncRecord.objects.bulk_create(rows, batch_size=500)

    def resolve_report_dir(self, cfg: CostSyncConfig) -> Path:
        path = Path(cfg.report_dir)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    def build_clients(self, cfg: CostSyncConfig):
        dear = DearClient(
            base_url=cfg.dear_base_url,
            account_id=cfg.dear_account_id,
            application_key=cfg.dear_application_key,
            page_size=cfg.page_size,
            timeout=cfg.request_timeout,
            max_retries=cfg.max_retries,
            rate_limit_per_minute=cfg.rate_limit_per_minute,
        )
        shopify = ShopifyClient(
            store_domain=cfg.shopify_store_domain,
            access_token=cfg.shopify_access_token,
            api_version=cfg.shopify_api_version,
            timeout=cfg.request_timeout,
            max_retries=cfg.max_retries,
            variant_query_batch_size=cfg.variant_batch_size,
        )
        return dear, shopify

    def build_sync_options(
        self,
        cfg: CostSyncConfig,
        *,
        dry_run: Optional[bool] = None,
        sku: Optional[str] = None,
        max_updates: Optional[int] = None,
        weekly: bool = False,
    ) -> SyncOptions:
        effective_dry_run = cfg.dry_run if dry_run is None else dry_run
        effective_max = (
            cfg.max_updates_per_run if max_updates is None else max_updates
        )
        opts = SyncOptions(
            dry_run=effective_dry_run,
            decimal_places=2,
            rounding_mode="ROUND_HALF_UP",
            tolerance=cfg.tolerance,
            max_updates_per_run=effective_max,
            include_inactive_products=cfg.include_inactive,
            single_sku=sku,
            expected_currency=cfg.currency,
        )
        if weekly:
            opts = effective_weekly_options(opts, cfg.weekly_mode)
        return opts

    def determine_status(self, counters: RunCounters) -> str:
        if counters.failed_updates > 0 or counters.api_errors > 0:
            return CostSyncRun.Status.COMPLETED_WITH_ERRORS
        return CostSyncRun.Status.SUCCESS

    # -- email ------------------------------------------------------------
    def set_email_configuration(self):
        try:
            email_host = JobConfiguration.objects.get(
                config_name="EMAIL_HOST"
            ).config_value
            email_port = JobConfiguration.objects.get(
                config_name="EMAIL_PORT"
            ).config_value
            email_host_user = JobConfiguration.objects.get(
                config_name="EMAIL_HOST_USER"
            ).config_value
            email_to_user = JobConfiguration.objects.get(
                config_name="EMAIL_TO_USER"
            ).config_value
            email_pass = JobConfiguration.objects.get(
                config_name="EMAIL_HOST_PASSWORD"
            )
            email_host_password = email_pass.decoded_email_password
        except JobConfiguration.DoesNotExist:
            email_host = config("EMAIL_HOST", default="")
            email_port = config("EMAIL_PORT", default=587)
            email_host_user = config("EMAIL_HOST_USER", default="")
            email_host_password = config("EMAIL_HOST_PASSWORD", default="")
            email_to_user = config("EMAIL_TO_USER", default="")

        settings.EMAIL_HOST = email_host
        settings.EMAIL_PORT = int(email_port) if email_port else 587
        settings.EMAIL_HOST_USER = email_host_user
        settings.EMAIL_HOST_PASSWORD = email_host_password
        settings.EMAIL_USE_TLS = True
        return email_host_user, email_to_user

    def send_report_email(
        self,
        *,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
        attachment_path: Optional[Path] = None,
    ) -> tuple[bool, Optional[str]]:
        try:
            email_from, email_to = self.set_email_configuration()
            if not email_to:
                return False, "EMAIL_TO_USER is empty"
            recipients = [u.strip() for u in email_to.split(",") if u.strip()]
            if not recipients:
                return False, "No email recipients"

            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=email_from,
                to=recipients,
            )
            if html_body:
                msg.attach_alternative(html_body, "text/html")
            if attachment_path and Path(attachment_path).is_file():
                with open(attachment_path, "rb") as fh:
                    msg.attach(
                        Path(attachment_path).name,
                        fh.read(),
                        "text/csv",
                    )
            msg.send(fail_silently=False)
            return True, None
        except Exception as exc:
            logger.exception("Cost sync email failed (non-fatal): %s", exc)
            return False, str(exc)

    def remove_report_file(self, report_path: Path) -> None:
        try:
            if report_path.is_file():
                report_path.unlink()
                logger.info("Removed cost sync report after email: %s", report_path)
        except OSError as exc:
            logger.warning("Could not remove report %s: %s", report_path, exc)

    # -- orchestration ----------------------------------------------------
    def execute_sync(
        self,
        *,
        run_type: str,
        dry_run: Optional[bool] = None,
        sku: Optional[str] = None,
        max_updates: Optional[int] = None,
        force_unlock: bool = False,
        weekly: bool = False,
        note: str = "",
    ) -> dict:
        """Run full sync pipeline. Returns a summary dict."""
        cfg = self.load_config()
        opts = self.build_sync_options(
            cfg,
            dry_run=dry_run,
            sku=sku,
            max_updates=max_updates,
            weekly=weekly,
        )

        mode_label = "DRY-RUN" if opts.dry_run else "LIVE"
        print(f"DEAR cost sync starting ({run_type}, {mode_label})")

        self.acquire_lock(force_unlock=force_unlock)
        run = None
        try:
            run = self.create_run(
                run_type=run_type,
                dry_run=opts.dry_run,
                note=note or f"{run_type} cost sync ({mode_label})",
            )
            dear, shopify = self.build_clients(cfg)
            outcome = SyncService(dear, shopify, opts).run()
            self.persist_records(run, outcome.records)

            report_path = write_csv_report(
                self.resolve_report_dir(cfg),
                str(run.id),
                run_type,
                outcome.records,
                include_unchanged=False,
            )
            status = self.determine_status(outcome.counters)
            summary = build_summary(
                str(run.id),
                run_type,
                opts.dry_run,
                outcome.counters,
                status,
                report_path,
            )
            print(summary)
            self.finalise_run(
                run,
                status=status,
                counters=outcome.counters,
                report_path=str(report_path),
                note=summary,
            )

            if cfg.email_enabled:
                problems = [
                    r
                    for r in outcome.records
                    if r.result in (Result.FAILED, Result.SKIPPED)
                ]
                html = build_html_summary(
                    str(run.id),
                    run_type,
                    opts.dry_run,
                    outcome.counters,
                    status,
                    problem_records=problems[:50],
                )
                sent, err = self.send_report_email(
                    subject=f"DEAR Cost Sync — {run_type} — {status}",
                    text_body=summary,
                    html_body=html,
                    attachment_path=report_path,
                )
                if sent:
                    self.remove_report_file(report_path)
                    run.report_path = ""
                    run.save(update_fields=["report_path"])
                    report_path = None
                else:
                    print(f"Email not sent: {err}")

            return {
                "run_id": str(run.id),
                "status": status,
                "dry_run": opts.dry_run,
                "counters": outcome.counters.as_dict(),
                "report_path": str(report_path) if report_path else "",
            }
        except Exception as exc:
            logger.exception("Cost sync failed: %s", exc)
            if run is not None:
                empty = RunCounters()
                self.finalise_run(
                    run,
                    status=CostSyncRun.Status.FAILED,
                    counters=empty,
                    error_message=str(exc),
                    note=f"Failed: {exc}",
                )
                if cfg.email_enabled:
                    self.send_report_email(
                        subject=f"DEAR Cost Sync — {run_type} — FAILED",
                        text_body=f"Cost sync failed:\n{exc}",
                    )
            raise
        finally:
            self.release_lock()
