# Generated manually for dear_cost_sync initial schema

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CostSyncLock',
            fields=[
                ('name', models.CharField(max_length=50, primary_key=True, serialize=False)),
                ('acquired_at', models.DateTimeField(blank=True, null=True)),
                ('pid', models.IntegerField(blank=True, null=True)),
                ('host', models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                'verbose_name': 'Cost Sync Lock',
                'verbose_name_plural': 'Cost Sync Locks',
            },
        ),
        migrations.CreateModel(
            name='CostSyncRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('run_type', models.CharField(choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('manual', 'Manual')], default='daily', max_length=20)),
                ('status', models.CharField(choices=[('Processing', 'Processing'), ('Success', 'Success'), ('CompletedWithErrors', 'Completed With Errors'), ('Failed', 'Failed')], default='Processing', max_length=30)),
                ('dry_run', models.BooleanField(default=True)),
                ('note', models.TextField(blank=True, null=True)),
                ('report_path', models.CharField(blank=True, max_length=500, null=True)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('counters_json', models.JSONField(blank=True, null=True)),
                ('records_retrieved', models.IntegerField(default=0)),
                ('records_processed', models.IntegerField(default=0)),
                ('records_updated', models.IntegerField(default=0)),
                ('records_failed', models.IntegerField(default=0)),
                ('records_skipped', models.IntegerField(default=0)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Cost Sync Run',
                'verbose_name_plural': 'Cost Sync Runs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='CostSyncRecord',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='created_at')),
                ('updated_at', models.DateTimeField(auto_now=True, db_column='updated_at')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('dear_product_id', models.CharField(blank=True, max_length=100, null=True)),
                ('sku', models.CharField(blank=True, db_index=True, max_length=255, null=True)),
                ('dear_name', models.CharField(blank=True, max_length=500, null=True)),
                ('dear_status', models.CharField(blank=True, max_length=50, null=True)),
                ('dear_average_cost', models.CharField(blank=True, max_length=50, null=True)),
                ('normalised_dear_cost', models.CharField(blank=True, max_length=50, null=True)),
                ('shopify_variant_id', models.CharField(blank=True, max_length=100, null=True)),
                ('shopify_inventory_item_id', models.CharField(blank=True, max_length=100, null=True)),
                ('shopify_product_id', models.CharField(blank=True, max_length=100, null=True)),
                ('shopify_product_title', models.CharField(blank=True, max_length=500, null=True)),
                ('previous_shopify_cost', models.CharField(blank=True, max_length=50, null=True)),
                ('new_shopify_cost', models.CharField(blank=True, max_length=50, null=True)),
                ('shopify_currency', models.CharField(blank=True, max_length=10, null=True)),
                ('action', models.CharField(choices=[('UPDATE', 'Update'), ('UNCHANGED', 'Unchanged'), ('SKIP', 'Skip')], default='SKIP', max_length=20)),
                ('result', models.CharField(choices=[('SUCCESS', 'Success'), ('DRY_RUN', 'Dry Run'), ('UNCHANGED', 'Unchanged'), ('SKIPPED', 'Skipped'), ('FAILED', 'Failed')], default='SKIPPED', max_length=20)),
                ('error_code', models.CharField(blank=True, max_length=100, null=True)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, db_column='created_by', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_created_by', to=settings.AUTH_USER_MODEL)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sync_records', to='dear_cost_sync.costsyncrun')),
                ('updated_by', models.ForeignKey(blank=True, db_column='updated_by', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(app_label)s_%(class)s_modified_by', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Cost Sync Record',
                'verbose_name_plural': 'Cost Sync Records',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='costsyncrecord',
            index=models.Index(fields=['run', 'sku'], name='dear_cost_s_run_id_cb6b3e_idx'),
        ),
    ]
