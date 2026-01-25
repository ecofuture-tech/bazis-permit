#!/usr/bin/env bash

echo "Gunicorn starting"
gunicorn -c file:deploy/config/admin.py --log-file=- --env DJANGO_SETTINGS_MODULE=sample.settings sample.wsgi:application
