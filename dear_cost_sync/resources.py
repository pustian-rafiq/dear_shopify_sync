from import_export import resources

from dear_cost_sync.models import CostSyncRecord


class CostSyncRecordResource(resources.ModelResource):
    class Meta:
        model = CostSyncRecord
        fields = (
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
        )
        export_order = fields
