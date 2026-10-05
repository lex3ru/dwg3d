#!/bin/sh
# A database and a role of the same name for every entry of TWIN_DATABASES;
# only that role may connect to it. Safe to run again: existing databases
# are left alone, passwords are set to the current values.
set -eu

for name in $TWIN_DATABASES; do
    var="TWIN_DB_PASSWORD_$(printf '%s' "$name" | tr 'a-z-' 'A-Z_')"
    password=$(eval "printf '%s' \"\${$var:-}\"")
    [ -n "$password" ] || { echo "ensure-databases: не задан $var" >&2; exit 1; }
    psql -q -v ON_ERROR_STOP=1 -v name="$name" -v password="$password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'name')
  WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'name') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'name', :'password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'name', :'name')
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'name') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'name') \gexec
SQL
    echo "ensure-databases: $name"
done
