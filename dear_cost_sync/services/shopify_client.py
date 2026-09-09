"""Shopify Admin GraphQL API client (API version 2026-07)."""

from __future__ import annotations

import logging
import random
import time
from decimal import Decimal
from typing import Iterable, Optional

import requests

from dear_cost_sync.services.decimal_utils import to_decimal
from dear_cost_sync.services.domain import ShopifyVariant
from dear_cost_sync.services.exceptions import (
    AuthenticationError,
    RateLimitError,
    ShopifyGraphQLError,
    ShopifyUserError,
    TransientApiError,
    ValidationError,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "dear-shopify-cost-sync/1.0.0 (+Shopify client)"

VARIANTS_BY_SKU_QUERY = """
query GetVariantsBySku($query: String!, $first: Int!, $after: String) {
  productVariants(first: $first, query: $query, after: $after) {
    nodes {
      id
      sku
      title
      inventoryItem {
        id
        sku
        unitCost { amount currencyCode }
      }
      product { id title status }
    }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()

INVENTORY_ITEM_UPDATE_MUTATION = """
mutation InventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
  inventoryItemUpdate(id: $id, input: $input) {
    inventoryItem {
      id
      unitCost { amount currencyCode }
    }
    userErrors { field message }
  }
}
""".strip()

INVENTORY_ITEM_READ_QUERY = """
query InventoryItemCost($id: ID!) {
  inventoryItem(id: $id) {
    id
    unitCost { amount currencyCode }
  }
}
""".strip()


def escape_sku_for_search(sku: str) -> str:
    if sku is None:
        raise ValidationError("SKU is None")
    if any(ord(ch) < 0x20 for ch in sku):
        raise ValidationError(
            "SKU contains control characters; refusing to build search"
        )
    escaped = sku.replace("\\", "\\\\").replace('"', '\\"')
    return f'sku:"{escaped}"'


class ShopifyClient:
    def __init__(
        self,
        store_domain: str,
        access_token: str,
        *,
        api_version: str = "2026-07",
        timeout: int = 30,
        max_retries: int = 5,
        variant_query_batch_size: int = 50,
        session: Optional[requests.Session] = None,
        sleep=time.sleep,
    ) -> None:
        self.endpoint = f"https://{store_domain}/admin/api/{api_version}/graphql.json"
        self.timeout = timeout
        self.max_retries = max_retries
        self.batch_size = max(1, int(variant_query_batch_size))
        self._sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
            }
        )

    def _execute(self, query: str, variables: dict, *, retry: bool) -> dict:
        attempt = 0
        while True:
            attempt += 1
            try:
                print("executing query with variables:", variables)
                print("executing query:", query)
                resp = self.session.post(
                    self.endpoint,
                    json={"query": query, "variables": variables},
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if retry:
                    self._maybe_retry(
                        attempt, TransientApiError(f"Shopify network error: {exc}")
                    )
                    continue
                raise TransientApiError(f"Shopify network error: {exc}") from exc

            status = resp.status_code
            if status in (401, 403):
                raise AuthenticationError(
                    f"Shopify authentication/permission error (HTTP {status})",
                    status_code=status,
                )
            if status == 429:
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if retry:
                    self._maybe_retry(
                        attempt,
                        RateLimitError(
                            "Shopify rate limit (HTTP 429)", retry_after=retry_after
                        ),
                        retry_after=retry_after,
                    )
                    continue
                raise RateLimitError(
                    "Shopify rate limit (HTTP 429)", retry_after=retry_after
                )
            if 500 <= status < 600:
                if retry:
                    self._maybe_retry(
                        attempt,
                        TransientApiError(f"Shopify server error (HTTP {status})"),
                    )
                    continue
                raise TransientApiError(f"Shopify server error (HTTP {status})")
            if status != 200:
                raise ShopifyGraphQLError(
                    f"Shopify unexpected HTTP {status}: {_safe_snippet(resp.text)}",
                    status_code=status,
                )

            try:
                body = resp.json()
            except ValueError as exc:
                raise ShopifyGraphQLError(
                    f"Shopify returned non-JSON body: {exc}", status_code=200
                ) from exc

            if _is_throttled(body):
                if retry:
                    self._maybe_retry(
                        attempt, RateLimitError("Shopify GraphQL THROTTLED")
                    )
                    continue
                raise RateLimitError("Shopify GraphQL THROTTLED")

            errors = body.get("errors")
            if errors:
                raise ShopifyGraphQLError(
                    f"Shopify GraphQL errors: {errors}", status_code=200
                )

            data = body.get("data")
            if data is None:
                raise ShopifyGraphQLError(
                    "Shopify GraphQL response missing 'data'", status_code=200
                )
            print("Shopify GraphQL response data:", data)
            return data

    def _maybe_retry(
        self, attempt: int, error: Exception, retry_after: float | None = None
    ) -> None:
        if attempt > self.max_retries:
            raise error
        delay = retry_after if retry_after is not None else _backoff(attempt)
        logger.warning(
            "Shopify retry %s/%s after error: %s (sleeping %.2fs)",
            attempt,
            self.max_retries,
            error,
            delay,
        )
        self._sleep(delay)

    def lookup_variants_by_skus(self, skus: Iterable[str]) -> dict[str, list[ShopifyVariant]]:
        requested = [s for s in skus if s is not None]
        result: dict[str, list[ShopifyVariant]] = {s: [] for s in requested}
        wanted = set(requested)

        for batch in _chunks(requested, self.batch_size):
            terms = []
            for s in batch:
                try:
                    terms.append(escape_sku_for_search(s))
                except ValidationError:
                    logger.warning(
                        "Skipping unsafe SKU in Shopify search (control chars)."
                    )
                    continue
            if not terms:
                continue
            query_expr = " OR ".join(terms)
            for variant in self._paginate_variants(query_expr):
                if variant.sku in wanted:
                    result[variant.sku].append(variant)
        return result

    def _paginate_variants(self, query_expr: str):
        after: Optional[str] = None
        pages = 0
        while True:
            pages += 1
            data = self._execute(
                VARIANTS_BY_SKU_QUERY,
                {"query": query_expr, "first": self.batch_size, "after": after},
                retry=True,
            )
            conn = data["productVariants"]
            print("product variants", conn)
            for node in conn["nodes"]:
                inv = node.get("inventoryItem") or {}
                unit = (inv.get("unitCost") or {}) if inv else {}
                amount = unit.get("amount")
                product = node.get("product") or {}
                yield ShopifyVariant(
                    variant_id=node["id"],
                    sku=node.get("sku"),
                    variant_title=node.get("title"),
                    inventory_item_id=inv.get("id"),
                    product_id=product.get("id"),
                    product_title=product.get("title"),
                    product_status=product.get("status"),
                    unit_cost_amount=(to_decimal(amount) if amount is not None else None),
                    unit_cost_currency=unit.get("currencyCode"),
                )
            page_info = conn.get("pageInfo") or {}
            if page_info.get("hasNextPage") and page_info.get("endCursor"):
                after = page_info["endCursor"]
                if pages > 100000:
                    raise ShopifyGraphQLError(
                        "Shopify variant pagination exceeded safety ceiling"
                    )
                continue
            break

    def read_inventory_item_cost(self, inventory_item_id: str) -> Optional[Decimal]:
        data = self._execute(
            INVENTORY_ITEM_READ_QUERY, {"id": inventory_item_id}, retry=True
        )
        item = data.get("inventoryItem")
        if not item:
            return None
        unit = item.get("unitCost") or {}
        amount = unit.get("amount")
        return to_decimal(amount) if amount is not None else None

    def update_inventory_item_cost(
        self, inventory_item_id: str, cost_string: str
    ) -> Decimal:
        variables = {"id": inventory_item_id, "input": {"cost": cost_string}}
        data = self._execute(INVENTORY_ITEM_UPDATE_MUTATION, variables, retry=False)
        payload = data.get("inventoryItemUpdate") or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            raise ShopifyUserError(f"inventoryItemUpdate userErrors: {user_errors}")

        item = payload.get("inventoryItem") or {}
        unit = item.get("unitCost") or {}
        returned = unit.get("amount")
        if returned is not None:
            mutation_cost = to_decimal(returned)
        else:
            mutation_cost = to_decimal(cost_string)

        # Requirements: after update, re-query to verify the final stored value.
        verified = self.read_inventory_item_cost(inventory_item_id)
        if verified is None:
            raise ShopifyUserError(
                "Update succeeded but verification read returned no cost"
            )
        if verified != mutation_cost:
            logger.warning(
                "Shopify cost mismatch after update for %s: mutation=%s verified=%s",
                inventory_item_id,
                mutation_cost,
                verified,
            )
        return verified


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _is_throttled(body: dict) -> bool:
    for err in body.get("errors", []) or []:
        code = (err.get("extensions") or {}).get("code")
        if code == "THROTTLED":
            return True
    return False


def _parse_retry_after(header: Optional[str]) -> Optional[float]:
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    exp = min(cap, base * (2 ** (attempt - 1)))
    return random.uniform(0.0, exp)


def _safe_snippet(text: str, limit: int = 300) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:limit]
