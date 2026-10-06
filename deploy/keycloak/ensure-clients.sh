#!/bin/sh
# The services' own accounts in Keycloak: a confidential client twin-svc-<name>
# with a service account for every entry of TWIN_SERVICE_CLIENTS. With its
# token a service calls another one when no user is behind the call (reacting
# to an event). Safe to run again: secrets are set to the current values.
# The addresses the client of the interface may return to follow TWIN_PUBLIC_URL,
# so a stack restored on a server with another address signs in there.
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

ui=$($kc get clients -r twin -q clientId=twin --fields id --format csv --noquotes | head -1)
if [ -n "$ui" ] && [ -n "${TWIN_PUBLIC_URL:-}" ]; then
    $kc update "clients/$ui" -r twin \
        -s "redirectUris=[\"$TWIN_PUBLIC_URL/auth/callback\",\"${TWIN_DEV_URL:-$TWIN_PUBLIC_URL}/auth/callback\"]" \
        -s "webOrigins=[\"$TWIN_PUBLIC_URL\"]" \
        -s "attributes.\"post.logout.redirect.uris\"=$TWIN_PUBLIC_URL/*##${TWIN_DEV_URL:-$TWIN_PUBLIC_URL}/*" >/dev/null
    echo "ensure-clients: twin → $TWIN_PUBLIC_URL"
fi

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
