from django.apps import AppConfig


class DearCostSyncConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dear_cost_sync'
    verbose_name = 'DEAR Cost Sync'

    # Daily Beat defaults to hour=2 under CELERY_TIMEZONE (Australia/Brisbane).
    # For true 02:00 America/Los_Angeles, set the PeriodicTask timezone in
    # django-celery-beat admin — do not change the global project timezone.
