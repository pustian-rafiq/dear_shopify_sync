import uuid

from django.db import models

from base.models import BaseModel


class CostSyncRun(models.Model):
    """One cost-sync job execution (daily / weekly / manual)."""

    class RunType(models.TextChoices):
        DAILY = 'daily', 'Daily'
        WEEKLY = 'weekly', 'Weekly'
        MANUAL = 'manual', 'Manual'

    class Status(models.TextChoices):
        PROCESSING = 'Processing', 'Processing'
        SUCCESS = 'Success', 'Success'
        COMPLETED_WITH_ERRORS = 'CompletedWithErrors', 'Completed With Errors'
        FAILED = 'Failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_type = models.CharField(max_length=20, choices=RunType.choices, default=RunType.DAILY)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PROCESSING)
    dry_run = models.BooleanField(default=True)
    note = models.TextField(null=True, blank=True)
    report_path = models.CharField(max_length=500, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    counters_json = models.JSONField(null=True, blank=True)

    records_retrieved = models.IntegerField(default=0)
    records_processed = models.IntegerField(default=0)
    records_updated = models.IntegerField(default=0)
    records_failed = models.IntegerField(default=0)
    records_skipped = models.IntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.run_type} {self.id} ({self.status})"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Cost Sync Run'
        verbose_name_plural = 'Cost Sync Runs'


class CostSyncRecord(BaseModel):
    """Per-SKU audit row for a cost sync run."""

    class Action(models.TextChoices):
        UPDATE = 'UPDATE', 'Update'
        UNCHANGED = 'UNCHANGED', 'Unchanged'
        SKIP = 'SKIP', 'Skip'

    class Result(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Success'
        DRY_RUN = 'DRY_RUN', 'Dry Run'
        UNCHANGED = 'UNCHANGED', 'Unchanged'
        SKIPPED = 'SKIPPED', 'Skipped'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        CostSyncRun, on_delete=models.CASCADE, related_name='sync_records'
    )
    dear_product_id = models.CharField(max_length=100, null=True, blank=True)
    sku = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    dear_name = models.CharField(max_length=500, null=True, blank=True)
    dear_status = models.CharField(max_length=50, null=True, blank=True)
    dear_average_cost = models.CharField(max_length=50, null=True, blank=True)
    normalised_dear_cost = models.CharField(max_length=50, null=True, blank=True)
    shopify_variant_id = models.CharField(max_length=100, null=True, blank=True)
    shopify_inventory_item_id = models.CharField(max_length=100, null=True, blank=True)
    shopify_product_id = models.CharField(max_length=100, null=True, blank=True)
    shopify_product_title = models.CharField(max_length=500, null=True, blank=True)
    previous_shopify_cost = models.CharField(max_length=50, null=True, blank=True)
    new_shopify_cost = models.CharField(max_length=50, null=True, blank=True)
    shopify_currency = models.CharField(max_length=10, null=True, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices, default=Action.SKIP)
    result = models.CharField(max_length=20, choices=Result.choices, default=Result.SKIPPED)
    error_code = models.CharField(max_length=100, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.sku or '(no sku)'} — {self.result}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Cost Sync Record'
        verbose_name_plural = 'Cost Sync Records'
        indexes = [
            models.Index(fields=['run', 'sku']),
        ]


class CostSyncLock(models.Model):
    """Single-instance lock to prevent overlapping cost-sync jobs."""

    name = models.CharField(max_length=50, primary_key=True)
    acquired_at = models.DateTimeField(null=True, blank=True)
    pid = models.IntegerField(null=True, blank=True)
    host = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        if self.acquired_at:
            return f"Lock {self.name} held since {self.acquired_at}"
        return f"Lock {self.name} free"

    @property
    def is_held(self):
        return self.acquired_at is not None

    class Meta:
        verbose_name = 'Cost Sync Lock'
        verbose_name_plural = 'Cost Sync Locks'
