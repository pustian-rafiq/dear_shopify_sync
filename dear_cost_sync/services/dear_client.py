"""DEAR Inventory (Cin7 Core) API client."""

from __future__ import annotations

import logging
import random
import time
from typing import Iterator, Optional

import requests

from dear_cost_sync.services.domain import DearProduct
from dear_cost_sync.services.exceptions import (
    AuthenticationError,
    DearApiError,
    RateLimitError,
    TransientApiError,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "dear-shopify-cost-sync/1.0.0 (+DEAR client)"


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(0, int(per_minute))
        self._min_interval = 60.0 / self.per_minute if self.per_minute > 0 else 0.0
        self._last_call = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()


class DearClient:
    def __init__(
        self,
        base_url: str,
        account_id: str,
        application_key: str,
        *,
        product_endpoint: str = "Product",
        page_size: int = 1000,
        timeout: int = 30,
        max_retries: int = 5,
        rate_limit_per_minute: int = 60,
        session: Optional[requests.Session] = None,
        sleep=time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.product_endpoint = product_endpoint.strip("/")
        self.page_size = page_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = RateLimiter(rate_limit_per_minute)
        self._sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "api-auth-accountid": account_id,
                "api-auth-applicationkey": application_key,
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            }
        )

    def _request(self, params: dict) -> dict:
        url = f"{self.base_url}/{self.product_endpoint}"
        attempt = 0
        while True:
            attempt += 1
            self.limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                self._maybe_retry(attempt, TransientApiError(f"DEAR network error: {exc}"))
                continue

            status = resp.status_code
            if status == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise DearApiError(
                        f"DEAR returned non-JSON body: {exc}", status_code=200
                    ) from exc

            if status in (401, 403):
                raise AuthenticationError(
                    f"DEAR authentication/permission error (HTTP {status})",
                    status_code=status,
                )
            if status == 429:
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                self._maybe_retry(
                    attempt,
                    RateLimitError("DEAR rate limit (HTTP 429)", retry_after=retry_after),
                    retry_after=retry_after,
                )
                continue
            if 500 <= status < 600:
                self._maybe_retry(
                    attempt, TransientApiError(f"DEAR server error (HTTP {status})")
                )
                continue

            raise DearApiError(
                f"DEAR request failed (HTTP {status}): {_safe_snippet(resp.text)}",
                status_code=status,
            )

    def _maybe_retry(
        self, attempt: int, error: Exception, retry_after: float | None = None
    ) -> None:
        if attempt > self.max_retries:
            raise error
        delay = retry_after if retry_after is not None else _backoff(attempt)
        logger.warning(
            "DEAR retry %s/%s after error: %s (sleeping %.2fs)",
            attempt,
            self.max_retries,
            error,
            delay,
        )
        self._sleep(delay)

    def iter_products(self) -> Iterator[DearProduct]:
        page = 1
        seen_ids: set[str] = set()
        total: Optional[int] = None
        emitted = 0

        while True:
            payload = self._request({"Page": page, "Limit": self.page_size})
            products = _extract_products(payload)
            if total is None:
                total = _extract_total(payload)

            if not products:
                logger.info("DEAR page %s returned 0 records; pagination complete.", page)
                break

            page_new = 0
            for raw in products:
                product = DearProduct.from_api(raw)
                if product.id and product.id in seen_ids:
                    continue
                if product.id:
                    seen_ids.add(product.id)
                page_new += 1
                emitted += 1
                yield product

            logger.info(
                "DEAR page %s: %s records (new=%s, cumulative=%s, total=%s)",
                page,
                len(products),
                page_new,
                emitted,
                total if total is not None else "?",
            )

            if page_new == 0:
                logger.warning(
                    "DEAR page %s contained only already-seen records; stopping.", page
                )
                break

            if len(products) < self.page_size:
                break
            if total is not None and emitted >= total:
                break

            page += 1
            if page > 100000:
                raise DearApiError(
                    "DEAR pagination exceeded safety ceiling (100000 pages)"
                )

    def fetch_all_products(self) -> list[DearProduct]:
        return list(self.iter_products())


def _extract_products(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        raise DearApiError("DEAR response was not a JSON object")
    for key in ("Products", "ProductList", "Items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    if isinstance(payload.get("Product"), list):
        return payload["Product"]
    raise DearApiError("DEAR response did not contain a recognised products array")


def _extract_total(payload: dict) -> Optional[int]:
    for key in ("Total", "TotalCount", "Count"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


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
