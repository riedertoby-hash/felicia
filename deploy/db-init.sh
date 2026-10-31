#!/bin/sh
# Runs once when the database volume is created (docker-entrypoint-initdb.d).
# The app gets its own role WITHOUT superuser/BYPASSRLS rights, so row-level security applies to it.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE "$APP_DB_USER" LOGIN PASSWORD '$APP_DB_PASSWORD' NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE DATABASE "$APP_DB_NAME" OWNER "$APP_DB_USER";
SQL
