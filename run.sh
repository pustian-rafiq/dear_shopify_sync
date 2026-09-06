#!/bin/sh

# pip install -r requirements.txt
# python manage.py makemigrations
# python manage.py migrate

# python manage.py test api/login
# python manage.py test api/static_configs
# python manage.py test api/core_banking
# python manage.py test api/workflows
# python manage.py test api/workflow_data
# python manage.py test api/xml_builders

python manage.py runserver 0.0.0.0:8080