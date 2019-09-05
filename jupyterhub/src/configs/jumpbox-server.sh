SERVER_URL="https://$KUBERNETES_SERVICE_HOST:$KUBERNETES_SERVICE_PORT"
ACCESS_TOKEN=`cat /var/run/secrets/kubernetes.io/serviceaccount/token`
NAMESPACE=`cat /var/run/secrets/kubernetes.io/serviceaccount/namespace`

NAMESPACE_URL="$SERVER_URL/apis/route.openshift.io/v1/namespaces/$NAMESPACE"
ROUTES_URL="$NAMESPACE_URL/routes/$APPLICATION_NAME-keycloak"

KEYCLOAK_NAME="$APPLICATION_NAME-keycloak"

KEYCLOAK_HOSTNAME=`curl -s -k -H "Authorization: Bearer $ACCESS_TOKEN" \
    $ROUTES_URL | jq -r '.spec.host'`

KEYCLOAK_REALM="homeroom"

export OAUTH2_TOKEN_URL="https://$KEYCLOAK_HOSTNAME/auth/realms/$KEYCLOAK_REALM/protocol/openid-connect/token"
export OAUTH2_AUTHORIZE_URL="https://$KEYCLOAK_HOSTNAME/auth/realms/$KEYCLOAK_REALM/protocol/openid-connect/auth"
export OAUTH2_USERDATA_URL="https://$KEYCLOAK_HOSTNAME/auth/realms/$KEYCLOAK_REALM/protocol/openid-connect/userinfo"

export OAUTH2_TLS_VERIFY="0"
export OAUTH_TLS_VERIFY="0"

export OAUTH2_USERNAME_KEY="preferred_username"
