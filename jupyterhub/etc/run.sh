#!/bin/bash

set -x

# Start the JupyterHub instance.

trap 'kill -TERM $PID' TERM INT

jupyterhub -f /opt/app-root/src/jupyterhub_config.py &

PID=$!
wait $PID
trap - TERM INT
wait $PID
STATUS=$?
exit $STATUS
