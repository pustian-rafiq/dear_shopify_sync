"""Dump JobConfiguration rows to JSON.

Usage:
  python manage.py dump_job_configurations -o deploy/job_configurations.json
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from job_config.models import JobConfiguration


class Command(BaseCommand):
    help = "Export all JobConfiguration rows to JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            default="deploy/job_configurations.json",
            help="Output JSON path",
        )

    def handle(self, *args, **options):
        rows = [
            {"config_name": r.config_name, "config_value": r.config_value or ""}
            for r in JobConfiguration.objects.order_by("config_name")
        ]
        path = Path(options["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(rows)} rows to {path}"))
