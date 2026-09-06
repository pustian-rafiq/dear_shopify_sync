"""Sync orchestration: DEAR -> normalise -> match -> compare -> update."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from dear_cost_sync.services.decimal_utils import (
    costs_differ,
    decimal_to_cost_string,
    normalise_cost,
)
from dear_cost_sync.services.domain import (
    Action,
    DearProduct,
    Result,
    RunCounters,
    ShopifyVariant,
    SyncRecord,
)
from dear_cost_sync.services.exceptions import (
    ApiError,
    CostSyncError,
    ShopifyGraphQLError,
    ShopifyUserError,
    TransientApiError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass
class SyncOptions:
    dry_run: bool = True
    decimal_places: int = 2
    rounding_mode: str = "ROUND_HALF_UP"
    tolerance: str = "0.00"
    max_updates_per_run: int = 0
    include_inactive_products: bool = False
    single_sku: Optional[str] = None
    expected_currency: str = "USD"


@dataclass
class SyncOutcome:
    records: list[SyncRecord]
    counters: RunCounters


class SyncService:
    def __init__(self, dear_client, shopify_client, options: SyncOptions) -> None:
        self.dear = dear_client
        self.shopify = shopify_client
        self.opts = options

    def run(self) -> SyncOutcome:
        started = time.monotonic()
        counters = RunCounters()
        records: list[SyncRecord] = []
        updates_applied = 0

        products = self.dear.fetch_all_products()
        counters.dear_products_retrieved = len(products)
        logger.info("Retrieved %s DEAR products", len(products))

        eligible: list[tuple[DearProduct, str, Decimal]] = []
        for product in products:
            record = self._new_record(product)

            if self.opts.single_sku is not None and product.sku != self.opts.single_sku:
                continue

            status = (product.status or "").strip()
            is_active = status.lower() == "active"
            if is_active:
                counters.active_products += 1
            if not is_active and not self.opts.include_inactive_products:
                if self.opts.single_sku is not None:
                    self._mark_skip(record, "INACTIVE", f"status={status!r} not Active")
                    counters.skipped_records += 1
                    records.append(record)
                continue

            if not product.sku or not str(product.sku).strip():
                counters.products_missing_sku += 1
                counters.skipped_records += 1
                self._mark_skip(record, "MISSING_SKU", "DEAR product has no SKU")
                records.append(record)
                continue

            try:
                normalised = normalise_cost(
                    product.average_cost_raw,
                    self.opts.decimal_places,
                    self.opts.rounding_mode,
                )
            except ValidationError as exc:
                counters.invalid_products += 1
                counters.skipped_records += 1
                record.dear_average_cost = _raw_to_str(product.average_cost_raw)
                self._mark_skip(record, "INVALID_COST", str(exc))
                records.append(record)
                continue

            record.dear_average_cost = _raw_to_str(product.average_cost_raw)
            record.normalised_dear_cost = decimal_to_cost_string(
                normalised, self.opts.decimal_places
            )
            eligible.append((product, product.sku, normalised))

        skus = [sku for (_, sku, _) in eligible]
        try:
            variant_map = self.shopify.lookup_variants_by_skus(skus) if skus else {}
        except ApiError as exc:
            counters.api_errors += 1
            logger.error("Shopify variant lookup failed: %s", exc)
            raise

        for product, sku, normalised in eligible:
            record = self._new_record(product)
            record.dear_average_cost = _raw_to_str(product.average_cost_raw)
            record.normalised_dear_cost = decimal_to_cost_string(
                normalised, self.opts.decimal_places
            )

            matches = variant_map.get(sku, [])
            if len(matches) == 0:
                counters.shopify_missing_matches += 1
                counters.skipped_records += 1
                self._mark_skip(
                    record, "NO_SHOPIFY_MATCH", "No Shopify variant with this SKU"
                )
                records.append(record)
                continue
            if len(matches) > 1:
                counters.duplicate_shopify_matches += 1
                counters.skipped_records += 1
                self._mark_skip(
                    record,
                    "AMBIGUOUS_MATCH",
                    f"{len(matches)} Shopify variants share SKU {sku!r}",
                )
                records.append(record)
                continue

            variant = matches[0]
            counters.shopify_matches += 1
            self._fill_variant(record, variant)

            if not variant.inventory_item_id:
                counters.skipped_records += 1
                self._mark_skip(
                    record, "NO_INVENTORY_ITEM", "Variant has no inventory item id"
                )
                records.append(record)
                continue

            if (
                variant.unit_cost_currency
                and self.opts.expected_currency
                and variant.unit_cost_currency != self.opts.expected_currency
            ):
                counters.skipped_records += 1
                self._mark_skip(
                    record,
                    "CURRENCY_MISMATCH",
                    f"Shopify currency {variant.unit_cost_currency} != expected "
                    f"{self.opts.expected_currency}",
                )
                records.append(record)
                continue

            previous = variant.unit_cost_amount
            record.previous_shopify_cost = _format_shopify_cost(
                previous, self.opts.decimal_places
            )

            if not costs_differ(normalised, previous, self.opts.tolerance):
                counters.costs_unchanged += 1
                record.action = Action.UNCHANGED
                record.result = Result.UNCHANGED
                record.new_shopify_cost = record.previous_shopify_cost
                record.processed_at_utc = utc_now_iso()
                records.append(record)
                continue

            counters.costs_changed += 1
            record.action = Action.UPDATE
            cost_string = record.normalised_dear_cost
            record.new_shopify_cost = cost_string

            if self.opts.dry_run:
                record.result = Result.DRY_RUN
                record.processed_at_utc = utc_now_iso()
                records.append(record)
                continue

            if (
                self.opts.max_updates_per_run > 0
                and updates_applied >= self.opts.max_updates_per_run
            ):
                counters.skipped_records += 1
                self._mark_skip(
                    record,
                    "MAX_UPDATES_REACHED",
                    f"max_updates_per_run={self.opts.max_updates_per_run} reached",
                )
                record.action = Action.UPDATE
                records.append(record)
                continue

            try:
                confirmed = self.shopify.update_inventory_item_cost(
                    variant.inventory_item_id, cost_string
                )
                record.result = Result.SUCCESS
                record.new_shopify_cost = decimal_to_cost_string(
                    confirmed, self.opts.decimal_places
                )
                counters.successful_updates += 1
                updates_applied += 1
            except (ShopifyUserError, ShopifyGraphQLError, TransientApiError) as exc:
                counters.failed_updates += 1
                if isinstance(exc, ApiError):
                    counters.api_errors += 1
                record.result = Result.FAILED
                record.new_shopify_cost = cost_string
                record.error_code = getattr(exc, "error_code", "UPDATE_FAILED")
                record.error_message = str(exc)
            except CostSyncError as exc:
                counters.failed_updates += 1
                record.result = Result.FAILED
                record.error_code = getattr(exc, "error_code", "UPDATE_FAILED")
                record.error_message = str(exc)

            record.processed_at_utc = utc_now_iso()
            records.append(record)

        counters.runtime_seconds = time.monotonic() - started
        return SyncOutcome(records=records, counters=counters)

    def _new_record(self, product: DearProduct) -> SyncRecord:
        return SyncRecord(
            sku=product.sku,
            dear_product_id=product.id or None,
            dear_name=product.name,
            dear_status=product.status,
            shopify_currency=self.opts.expected_currency,
        )

    @staticmethod
    def _fill_variant(record: SyncRecord, variant: ShopifyVariant) -> None:
        record.shopify_variant_id = variant.variant_id
        record.shopify_inventory_item_id = variant.inventory_item_id
        record.shopify_product_id = variant.product_id
        record.shopify_product_title = variant.product_title
        if variant.unit_cost_currency:
            record.shopify_currency = variant.unit_cost_currency

    @staticmethod
    def _mark_skip(record: SyncRecord, code: str, message: str) -> None:
        record.action = Action.SKIP
        record.result = Result.SKIPPED
        record.error_code = code
        record.error_message = message
        record.processed_at_utc = utc_now_iso()


def _raw_to_str(value) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _format_shopify_cost(value, decimal_places: int) -> Optional[str]:
    """Format Shopify unit cost for reports; None means unset in Shopify."""
    if value is None:
        return None
    return decimal_to_cost_string(value, decimal_places)
