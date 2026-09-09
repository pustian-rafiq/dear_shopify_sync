"""Report generation: detailed CSV + human-readable summary."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from dear_cost_sync.services.domain import Action, Result, RunCounters, SyncRecord

CSV_COLUMNS = [
    "run_id",
    "run_type",
    "timestamp",
    "dear_product_id",
    "sku",
    "dear_product_name",
    "dear_status",
    "original_average_cost",
    "normalised_dear_cost",
    "shopify_variant_id",
    "shopify_inventory_item_id",
    "shopify_product_id",
    "shopify_product_title",
    "shopify_product_status",
    "previous_shopify_cost",
    "new_shopify_cost",
    "currency",
    "action",
    "result",
    "error_code",
    "error_message",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")


def write_csv_report(
    output_dir: Path,
    run_id: str,
    run_type: str,
    records: Iterable[SyncRecord],
    *,
    include_unchanged: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _iso_now()
    file_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f"cost_sync_{run_type}_run_{file_stamp}.csv"
    path = output_dir / fname

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in records:
            if not include_unchanged and r.result == Result.UNCHANGED:
                continue
            writer.writerow(
                {
                    "run_id": run_id,
                    "run_type": run_type,
                    "timestamp": r.processed_at_utc or timestamp,
                    "dear_product_id": r.dear_product_id or "",
                    "sku": r.sku or "",
                    "dear_product_name": r.dear_name or "",
                    "dear_status": r.dear_status or "",
                    "original_average_cost": r.dear_average_cost or "",
                    "normalised_dear_cost": r.normalised_dear_cost or "",
                    "shopify_variant_id": r.shopify_variant_id or "",
                    "shopify_inventory_item_id": r.shopify_inventory_item_id or "",
                    "shopify_product_id": r.shopify_product_id or "",
                    "shopify_product_title": r.shopify_product_title or "",
                    "shopify_product_status": r.shopify_product_status or "",
                    "previous_shopify_cost": r.previous_shopify_cost or "",
                    "new_shopify_cost": r.new_shopify_cost or "",
                    "currency": r.shopify_currency or "",
                    "action": r.action.value if isinstance(r.action, Action) else r.action,
                    "result": r.result.value if isinstance(r.result, Result) else r.result,
                    "error_code": r.error_code or "",
                    "error_message": r.error_message or "",
                }
            )
    return path


def build_summary(
    run_id: str,
    run_type: str,
    dry_run: bool,
    counters: RunCounters,
    status: str,
    report_path: Optional[Path],
) -> str:
    c = counters
    mode = "DRY-RUN (no Shopify writes)" if dry_run else "LIVE"
    lines = [
        "DEAR -> Shopify Cost Sync — Run Summary",
        "=" * 44,
        f"Run ID           : {run_id}",
        f"Run type         : {run_type}",
        f"Mode             : {mode}",
        f"Status           : {status}",
        f"Completed (UTC)  : {_iso_now()}",
        f"Runtime (s)      : {c.runtime_seconds:.3f}",
        "",
        "Counts",
        "-" * 44,
        f"DEAR products retrieved  : {c.dear_products_retrieved}",
        f"Active products          : {c.active_products}",
        f"Invalid products         : {c.invalid_products}",
        f"Products missing SKU     : {c.products_missing_sku}",
        f"Shopify matches          : {c.shopify_matches}",
        f"Shopify missing matches  : {c.shopify_missing_matches}",
        f"Duplicate Shopify matches: {c.duplicate_shopify_matches}",
        f"Costs unchanged          : {c.costs_unchanged}",
        f"Costs changed            : {c.costs_changed}",
        f"Successful updates       : {c.successful_updates}",
        f"Failed updates           : {c.failed_updates}",
        f"Skipped records          : {c.skipped_records}",
        f"API errors               : {c.api_errors}",
        "",
        f"Report CSV       : {report_path if report_path else '(none)'}",
    ]
    return "\n".join(lines)


def build_html_summary(
    run_id: str,
    run_type: str,
    dry_run: bool,
    counters: RunCounters,
    status: str,
    problem_records: Iterable[SyncRecord] = (),
) -> str:
    c = counters
    mode = "DRY-RUN" if dry_run else "LIVE"
    rows = "".join(
        f"<tr><td>{k}</td><td style='text-align:right'>{v}</td></tr>"
        for k, v in c.as_dict().items()
    )
    problems = list(problem_records)
    problem_html = ""
    if problems:
        prows = "".join(
            f"<tr><td>{(r.sku or '')}</td><td>{r.result.value}</td>"
            f"<td>{r.error_code or ''}</td><td>{(r.error_message or '')}</td></tr>"
            for r in problems
        )
        problem_html = (
            "<h3>Skipped / Failed records</h3>"
            "<table border='1' cellpadding='4' cellspacing='0'>"
            "<tr><th>SKU</th><th>Result</th><th>Code</th><th>Message</th></tr>"
            f"{prows}</table>"
        )
    return (
        f"<h2>DEAR &rarr; Shopify Cost Sync</h2>"
        f"<p><b>Run {run_id}</b> — {run_type} — <b>{mode}</b> — "
        f"status: <b>{status}</b></p>"
        "<table border='1' cellpadding='4' cellspacing='0'>"
        f"{rows}</table>{problem_html}"
    )
