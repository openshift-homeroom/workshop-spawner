#!/bin/bash

set -x

# Read any custom environment variables.

. /opt/app-root/src/jupyterhub_config.sh

# Start the JupyterHub instance.

trap 'kill -TERM $PID' TERM INT

jupyterhub -f /opt/app-root/src/jupyterhub_config.py &

PID=$!
wait $PID
trap - TERM INT
wait $PID
STATUS=$?
exit $STATUS
