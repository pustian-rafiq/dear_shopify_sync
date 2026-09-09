from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dear_cost_sync", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="costsyncrecord",
            name="shopify_product_status",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
