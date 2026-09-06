import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dear_to_shopify.settings')

app = Celery('dear_to_shopify')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
