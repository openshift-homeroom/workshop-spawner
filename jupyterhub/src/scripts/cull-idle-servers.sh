#!/bin/bash

exec python `dirname $0`/cull-idle-servers.py "$@"
