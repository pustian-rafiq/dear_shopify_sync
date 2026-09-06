"""Load JobConfiguration rows from a JSON file (upsert by config_name).

Usage:
  python manage.py load_job_configurations deploy/job_configurations.json
  docker compose exec dear_to_shopify python manage.py load_job_configurations deploy/job_configurations.json
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from job_config.models import JobConfiguration


class Command(BaseCommand):
    help = "Upsert JobConfiguration records from a JSON file"

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Path to JSON list of {config_name, config_value} objects",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing",
        )

    def handle(self, *args, **options):
        path = Path(options["json_path"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise CommandError("JSON root must be a list")

        created = updated = skipped = 0
        for row in payload:
            if not isinstance(row, dict):
                raise CommandError(f"Invalid row (not an object): {row!r}")
            name = (row.get("config_name") or "").strip()
            value = row.get("config_value")
            if not name:
                raise CommandError(f"Missing config_name in row: {row!r}")
            if value is None:
                value = ""

            existing = JobConfiguration.objects.filter(config_name=name).first()
            if existing and existing.config_value == value:
                skipped += 1
                self.stdout.write(f"SKIP  {name}")
                continue

            if options["dry_run"]:
                action = "UPDATE" if existing else "CREATE"
                self.stdout.write(f"{action} {name}")
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            # update()/bulk_create bypass Model.save() so EMAIL_HOST_PASSWORD
            # is not base64-encoded a second time when the fixture already
            # stores the encoded value from the source DB.
            if existing:
                JobConfiguration.objects.filter(pk=existing.pk).update(
                    config_value=value
                )
                updated += 1
                self.stdout.write(self.style.SUCCESS(f"UPDATE {name}"))
            else:
                JobConfiguration.objects.bulk_create(
                    [JobConfiguration(config_name=name, config_value=value)]
                )
                created += 1
                self.stdout.write(self.style.SUCCESS(f"CREATE {name}"))

        self.stdout.write(
            self.style.NOTICE(
                f"Done. created={created} updated={updated} skipped={skipped}"
                + (" (dry-run)" if options["dry_run"] else "")
            )
        )
