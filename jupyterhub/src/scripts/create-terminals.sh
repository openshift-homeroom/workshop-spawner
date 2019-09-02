#!/bin/bash

# Some bash functions for common tasks.

trim()
{
    local trimmed="$1"

    # Strip leading space.
    trimmed="${trimmed## }"
    # Strip trailing space.
    trimmed="${trimmed%% }"

    echo "$trimmed"
}

# Script can optionally be passed the arguments. If not supplied the
# user will be prompted to supply them.

if [ "$#" -ge 1 ]; then
    NUMBER_OF_USERS=$1
    shift
else
    read -p "Number of users: " NUMBER_OF_USERS
fi

NUMBER_OF_USERS=$(trim `echo $NUMBER_OF_USERS`)

if [ "$NUMBER_OF_USERS" == "" ]; then
    echo "ERROR: number of users cannot be empty."
    exit 1
fi

if ! [[ $NUMBER_OF_USERS =~ ^[0-9]*$ ]]; then
    echo "ERROR: Invalid value $NUMBER_OF_USERS."
    exit 1
fi

if [ "$#" -ge 1 ]; then
    ACCESS_TOKEN=$1
    shift
else
    read -p "Access token: " ACCESS_TOKEN
fi

ACCESS_TOKEN=$(trim `echo $ACCESS_TOKEN`)

if [ "$ACCESS_TOKEN" == "" ]; then
    echo "ERROR: access token cannot be empty."
    exit 1
fi

if [ "$#" -ge 1 ]; then
    APPLICATION_NAME=$1
    shift
else
    read -p "Application name: " APPLICATION_NAME
fi

APPLICATION_NAME=$(trim `echo $APPLICATION_NAME`)

if [ "$APPLICATION_NAME" == "" ]; then
    echo "ERROR: application name cannot be empty."
    exit 1
fi

if [ "$#" -ge 1 ]; then
    DO_UPDATE=y
    CONTINUE_PROMPT=n
fi

if [ x"$CONTINUE_PROMPT" != x"n" ]; then
    read -p "Continue? [y/N] " DO_UPDATE
fi

if ! [[ $DO_UPDATE =~ ^[Yy]$ ]]; then
    exit 1
fi

# Assumed that 'oc' is in the current path and that the script is being
# check that we can find the deployment in the project.

oc get "dc/$APPLICATION_NAME" > /dev/null 2>&1

if [ "$?" != "0" ]; then
    echo "ERROR: Cannot find JupyterHub deployment."
    exit 1
fi

# Lookup up the URL endpoint for the JupyterHub instance.

REST_API_HOST=`oc get "route/$APPLICATION_NAME" --template='{{.spec.host}}'`

if [ "$?" != "0" ]; then
    echo "ERROR: Cannot retrieve REST API host for $APPLICATION_NAME."
    exit 1
fi

REST_API_URL="https://$REST_API_HOST/hub/api"

# Create the terminal via REST API.

for i in `seq 1 $NUMBER_OF_USERS`; do

    echo "Creating user user$i"

    python -c "import json; \
        print(json.dumps({'usernames':['user$i']}))" > /tmp/user$$.json

    curl -k -H "Authorization: token $ACCESS_TOKEN" -X POST \
        -d @/tmp/user$$.json "$REST_API_URL/users"

    rm -f /tmp/users$$.json

    echo "Spawn terminal for user$i"

    curl -k -H "Authorization: token $ACCESS_TOKEN" -X POST \
        "$REST_API_URL/users/user$i/server"

    echo "Sleeping 3 seconds"

    sleep 3
done

echo
