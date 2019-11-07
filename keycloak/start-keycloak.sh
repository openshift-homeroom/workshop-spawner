#!/bin/bash

set -x

SERVER_URL="https://$KUBERNETES_SERVICE_HOST:$KUBERNETES_SERVICE_PORT"
TOKEN=`cat /var/run/secrets/kubernetes.io/serviceaccount/token`
NAMESPACE=`cat /var/run/secrets/kubernetes.io/serviceaccount/namespace`

NAMESPACE_URL="$SERVER_URL/apis/route.openshift.io/v1/namespaces/$NAMESPACE"
ROUTES_URL="$NAMESPACE_URL/routes/$SPAWNER_APPLICATION"

SPAWNER_HOSTNAME=`curl -s -k -H "Authorization: Bearer $TOKEN" $ROUTES_URL | \
    grep '"host"' | head -1 | sed -e 's/^.*host": "//' -e 's/".*//'`

KEYCLOAK_ARGS=

cat /realm.json | sed \
    -e "s/{{ *SPAWNER_HOSTNAME *}}/$SPAWNER_HOSTNAME/g" \
    -e "s/{{ *OAUTH_CLIENT_SECRET *}}/$OAUTH_CLIENT_SECRET/g" > /tmp/realm.json

KEYCLOAK_ARGS="$KEYCLOAK_ARGS -Dkeycloak.import=/tmp/realm.json"
KEYCLOAK_ARGS="$KEYCLOAK_ARGS -Dkeycloak.migration.strategy=IGNORE_EXISTING"

exec /opt/jboss/tools/docker-entrypoint.sh $KEYCLOAK_ARGS "$@"
