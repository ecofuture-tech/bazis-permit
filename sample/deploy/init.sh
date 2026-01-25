#!/usr/bin/env bash


# database processing
if chmod 744 deploy/db.sh && deploy/db.sh; then
  echo "Database processed correctly"
else
  echo "Database processing error"
  exit 1
fi


echo "Collecting static files"
if python manage.py collectstatic --noinput; then
  echo "Success: Collecting static files"
else
  echo "Error: Collecting static files"
  exit 1
fi


echo "Building schemas.json"
if python manage.py schemas_build; then
  echo "Success: Building schemas.json"
else
  echo "Error: Building schemas.json"
  exit 1
fi


echo "Checking/creating superuser"
if python manage.py admin_create; then
  echo "Success: Checking/creating superuser"
else
  echo "Error: Checking/creating superuser"
  exit 1
fi


echo "Initialization completed"