from django.contrib import admin
from import_export.admin import ExportActionMixin
from import_export.formats import base_formats
from rangefilter.filters import DateRangeFilter

from dear_cost_sync.models import CostSyncLock, CostSyncRecord, CostSyncRun
from dear_cost_sync.resources import CostSyncRecordResource
from dear_cost_sync.tasks import (
    daily_cost_sync,
    force_unlock_cost_sync,
    run_cost_sync_manual,
    weekly_cost_sync,
)


class CostSyncRunAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "run_type",
        "status",
        "dry_run",
        "records_retrieved",
        "records_updated",
        "records_failed",
        "records_skipped",
        "started_at",
        "completed_at",
        "created_at",
    ]
    list_filter = ["run_type", "status", "dry_run", ("created_at", DateRangeFilter)]
    search_fields = ["id", "note", "error_message", "report_path"]
    readonly_fields = [
        "id",
        "run_type",
        "status",
        "dry_run",
        "note",
        "report_path",
        "error_message",
        "counters_json",
        "records_retrieved",
        "records_processed",
        "records_updated",
        "records_failed",
        "records_skipped",
        "started_at",
        "completed_at",
        "created_at",
    ]
    ordering = ["-created_at"]
    actions = [
        "run_daily_dry_run",
        "run_daily_live",
        "run_weekly_reconciliation",
        "force_unlock_lock",
    ]

    @admin.action(description="Run daily cost sync (dry-run)")
    def run_daily_dry_run(self, request, queryset):
        daily_cost_sync.delay(dry_run=True)
        self.message_user(request, "Queued daily cost sync (dry-run).")

    @admin.action(description="Run daily cost sync (LIVE)")
    def run_daily_live(self, request, queryset):
        daily_cost_sync.delay(dry_run=False)
        self.message_user(request, "Queued daily cost sync (LIVE).")

    @admin.action(description="Run weekly reconciliation")
    def run_weekly_reconciliation(self, request, queryset):
        weekly_cost_sync.delay()
        self.message_user(request, "Queued weekly cost reconciliation.")

    @admin.action(description="Force unlock cost sync lock")
    def force_unlock_lock(self, request, queryset):
        force_unlock_cost_sync.delay()
        self.message_user(request, "Queued force-unlock of cost sync lock.")


class CostSyncRecordAdmin(ExportActionMixin, admin.ModelAdmin):
    resource_class = CostSyncRecordResource
    list_display = [
        "sku",
        "run",
        "dear_name",
        "shopify_product_status",
        "normalised_dear_cost",
        "previous_shopify_cost",
        "new_shopify_cost",
        "action",
        "result",
        "error_code",
        "processed_at",
        "created_at",
    ]
    list_filter = [
        "action",
        "result",
        "error_code",
        "shopify_product_status",
        ("created_at", DateRangeFilter),
    ]
    search_fields = [
        "sku",
        "dear_product_id",
        "dear_name",
        "shopify_variant_id",
        "shopify_inventory_item_id",
        "shopify_product_status",
        "error_message",
    ]
    readonly_fields = [
        "id",
        "run",
        "dear_product_id",
        "sku",
        "dear_name",
        "dear_status",
        "dear_average_cost",
        "normalised_dear_cost",
        "shopify_variant_id",
        "shopify_inventory_item_id",
        "shopify_product_id",
        "shopify_product_title",
        "shopify_product_status",
        "previous_shopify_cost",
        "new_shopify_cost",
        "shopify_currency",
        "action",
        "result",
        "error_code",
        "error_message",
        "processed_at",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]
    raw_id_fields = ["run"]
    actions = ["run_manual_dry_run"]

    @admin.action(description="Queue manual dry-run sync")
    def run_manual_dry_run(self, request, queryset):
        run_cost_sync_manual.delay(dry_run=True)
        self.message_user(request, "Queued manual cost sync (dry-run).")

    def get_export_formats(self):
        formats = (base_formats.CSV,)
        return [f for f in formats if f().can_export()]


class CostSyncLockAdmin(admin.ModelAdmin):
    list_display = ["name", "acquired_at", "pid", "host"]
    readonly_fields = ["name", "acquired_at", "pid", "host"]
    actions = ["force_unlock"]

    @admin.action(description="Force unlock selected locks")
    def force_unlock(self, request, queryset):
        force_unlock_cost_sync.delay()
        self.message_user(request, "Queued force-unlock.")


admin.site.register(CostSyncRun, CostSyncRunAdmin)
admin.site.register(CostSyncRecord, CostSyncRecordAdmin)
admin.site.register(CostSyncLock, CostSyncLockAdmin)
