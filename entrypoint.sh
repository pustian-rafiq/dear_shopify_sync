#!/bin/sh
set -e

cd /opt/app

mkdir -p reports/dear_cost_sync media static/static_root

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Starting gunicorn..."
exec gunicorn --chdir=/opt/app \
    --workers=3 \
    --threads=4 \
    --worker-class=gthread \
    --bind 0.0.0.0:5000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --log-level=info \
    --error-logfile - \
    --access-logfile - \
    --capture-output \
    dear_to_shopify.wsgi:application
