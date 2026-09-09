"""Domain dataclasses and enums shared by cost-sync services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class Action(str, Enum):
    UPDATE = "UPDATE"
    UNCHANGED = "UNCHANGED"
    SKIP = "SKIP"


class Result(str, Enum):
    SUCCESS = "SUCCESS"
    DRY_RUN = "DRY_RUN"
    UNCHANGED = "UNCHANGED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass
class DearProduct:
    id: str
    sku: Optional[str]
    name: Optional[str]
    status: Optional[str]
    average_cost_raw: object
    last_modified_on: Optional[str]

    @classmethod
    def from_api(cls, payload: dict) -> "DearProduct":
        return cls(
            id=str(payload.get("ID") or "").strip(),
            sku=(payload.get("SKU") if payload.get("SKU") is not None else None),
            name=payload.get("Name"),
            status=payload.get("Status"),
            average_cost_raw=payload.get("AverageCost"),
            last_modified_on=payload.get("LastModifiedOn"),
        )


# Shopify Product.status values we allow cost updates for.
SHOPIFY_ELIGIBLE_PRODUCT_STATUSES = frozenset({"ACTIVE", "DRAFT"})


@dataclass
class ShopifyVariant:
    variant_id: str
    sku: Optional[str]
    variant_title: Optional[str]
    inventory_item_id: str
    product_id: Optional[str]
    product_title: Optional[str]
    product_status: Optional[str]
    unit_cost_amount: Optional[Decimal]
    unit_cost_currency: Optional[str]


@dataclass
class SyncRecord:
    sku: Optional[str]
    dear_product_id: Optional[str] = None
    dear_name: Optional[str] = None
    dear_status: Optional[str] = None
    dear_average_cost: Optional[str] = None
    normalised_dear_cost: Optional[str] = None
    shopify_variant_id: Optional[str] = None
    shopify_inventory_item_id: Optional[str] = None
    shopify_product_id: Optional[str] = None
    shopify_product_title: Optional[str] = None
    shopify_product_status: Optional[str] = None
    previous_shopify_cost: Optional[str] = None
    new_shopify_cost: Optional[str] = None
    shopify_currency: Optional[str] = None
    action: Action = Action.SKIP
    result: Result = Result.SKIPPED
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    processed_at_utc: Optional[str] = None


@dataclass
class RunCounters:
    dear_products_retrieved: int = 0
    active_products: int = 0
    invalid_products: int = 0
    products_missing_sku: int = 0
    shopify_matches: int = 0
    shopify_missing_matches: int = 0
    duplicate_shopify_matches: int = 0
    costs_unchanged: int = 0
    costs_changed: int = 0
    successful_updates: int = 0
    failed_updates: int = 0
    skipped_records: int = 0
    api_errors: int = 0
    runtime_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "dear_products_retrieved": self.dear_products_retrieved,
            "active_products": self.active_products,
            "invalid_products": self.invalid_products,
            "products_missing_sku": self.products_missing_sku,
            "shopify_matches": self.shopify_matches,
            "shopify_missing_matches": self.shopify_missing_matches,
            "duplicate_shopify_matches": self.duplicate_shopify_matches,
            "costs_unchanged": self.costs_unchanged,
            "costs_changed": self.costs_changed,
            "successful_updates": self.successful_updates,
            "failed_updates": self.failed_updates,
            "skipped_records": self.skipped_records,
            "api_errors": self.api_errors,
            "runtime_seconds": round(self.runtime_seconds, 3),
        }
