"""Weekly reconciliation option derivation."""

from __future__ import annotations

import logging
from dataclasses import replace

from dear_cost_sync.services.sync_service import SyncOptions

logger = logging.getLogger(__name__)

RECONCILE_ONLY = "reconciliation_only"
RECONCILE_AND_CORRECT = "reconcile_and_correct"


def effective_weekly_options(base: SyncOptions, weekly_mode: str) -> SyncOptions:
    mode = (weekly_mode or RECONCILE_ONLY).strip()
    if mode == RECONCILE_AND_CORRECT:
        logger.info(
            "Weekly mode: reconcile_and_correct (updates honour dry-run/live flags)"
        )
        return base
    if mode != RECONCILE_ONLY:
        logger.warning(
            "Unknown weekly_mode %r; defaulting to reconciliation_only", weekly_mode
        )
    logger.info(
        "Weekly mode: reconciliation_only (forcing dry-run; no Shopify writes)"
    )
    return replace(base, dry_run=True)
