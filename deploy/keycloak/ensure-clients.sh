#!/bin/sh
# The services' own accounts in Keycloak: a confidential client twin-svc-<name>
# with a service account for every entry of TWIN_SERVICE_CLIENTS. With its
# token a service calls another one when no user is behind the call (reacting
# to an event). Safe to run again: secrets are set to the current values.
set -eu
kc=/opt/keycloak/bin/kcadm.sh
export KCADM_CONFIG=/tmp/kcadm.config

n=0
until $kc config credentials --server "$KC_URL" --realm master --user "$KEYCLOAK_ADMIN" \
        --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null 2>&1; do
    n=$((n + 1))
    [ "$n" -lt 90 ] || { echo "ensure-clients: Keycloak не отвечает" >&2; exit 1; }
    sleep 2
done
until $kc get realms/twin >/dev/null 2>&1; do sleep 2; done      # the realm import may still be running

for name in $TWIN_SERVICE_CLIENTS; do
    var="TWIN_SVC_SECRET_$(printf '%s' "$name" | tr 'a-z-' 'A-Z_')"
    secret=$(eval "printf '%s' \"\${$var:-}\"")
    [ -n "$secret" ] || { echo "ensure-clients: не задан $var" >&2; exit 1; }
    client="twin-svc-$name"
    id=$($kc get clients -r twin -q clientId="$client" --fields id --format csv --noquotes | head -1)
    if [ -z "$id" ]; then
        $kc create clients -r twin -s clientId="$client" -s name="Сервис $name" -s enabled=true \
            -s publicClient=false -s serviceAccountsEnabled=true -s standardFlowEnabled=false \
            -s directAccessGrantsEnabled=false -s secret="$secret" >/dev/null
    else
        $kc update "clients/$id" -r twin -s secret="$secret" -s enabled=true >/dev/null
    fi
    echo "ensure-clients: $client"
done
