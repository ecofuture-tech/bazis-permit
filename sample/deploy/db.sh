#!/usr/bin/env bash

# Wait for PostgreSQL database to start
until pg_isready -h "$BS_DATABASES__DEFAULT__HOST" -p "$BS_DATABASES__DEFAULT__PORT"; do
  echo "Waiting for postgres..."
  sleep 2
done
echo "Postgres is running, continuing"

# Set database password
export PGPASSWORD="$BS_DATABASES__DEFAULT__PASSWORD"

# Function to execute SQL commands
db_sql(){
    if echo "$1" | psql -h "$BS_DATABASES__DEFAULT__HOST" -p "$BS_DATABASES__DEFAULT__PORT" -U "$BS_DATABASES__DEFAULT__USER" -d postgres; then
      echo "Success: $1"
    else
      echo "Error: $1"
      exit 1
    fi
}

# Check if database exists
db_exists(){
  echo "SELECT 1 FROM pg_database WHERE datname='$1'" | psql -tA -h "$BS_DATABASES__DEFAULT__HOST" -p "$BS_DATABASES__DEFAULT__PORT" -U "$BS_DATABASES__DEFAULT__USER" -d postgres
}

# Create database if it doesn't exist
db_create() {
  if [[ "$(db_exists "$1")" == '1' ]]; then
    echo "Database already exists: $1"
  else
    db_sql "CREATE DATABASE \"$1\""
  fi
}

echo "Creating databases..."
db_create "$BS_DATABASES__DEFAULT__NAME"

echo "Configuring user $BS_DATABASES__DEFAULT__USER..."
db_sql "ALTER ROLE \"$BS_DATABASES__DEFAULT__USER\" SET client_encoding TO 'utf8'"
db_sql "ALTER ROLE \"$BS_DATABASES__DEFAULT__USER\" SET default_transaction_isolation TO 'read committed'"
db_sql "ALTER ROLE \"$BS_DATABASES__DEFAULT__USER\" SET timezone TO 'UTC'"

echo "Checking project"
if python manage.py constance list; then
 echo "Success: Project check"
else
 echo "Error: Project check"
 exit 1

fi

echo "Stopping triggers"
if python manage.py pgtrigger uninstall; then
 echo "Success: Stopping triggers"
else
 echo "Error: Stopping triggers"
#  exit 1
fi


echo "Running migrations"
if python manage.py migrate; then
  echo "Success: migrations"
else
  echo "Error: migrations"
  exit 1
fi


echo "Installing triggers"
if python manage.py pgtrigger install; then
  echo "Success: Installing triggers"
else
  echo "Error: Installing triggers"
  exit 1
fi