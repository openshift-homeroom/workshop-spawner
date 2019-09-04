source scl_source enable rh-python36

export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=UTF-8
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export PIP_NO_CACHE_DIR=off

if [ -f /opt/app-root/bin/activate ]; then
    source /opt/app-root/bin/activate
fi
