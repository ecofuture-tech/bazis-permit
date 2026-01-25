#!/usr/bin/env bash

echo "Gunicorn starting"
gunicorn -c file:deploy/config/app.py --log-file=- sample.main:app -k uvicorn.workers.UvicornWorker

