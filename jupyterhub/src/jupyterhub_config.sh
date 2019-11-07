CONFIGURATION_TYPE=${CONFIGURATION_TYPE:-hosted-workshop}

if [ -f /opt/app-root/src/configs/${CONFIGURATION_TYPE}.sh ]; then
    . /opt/app-root/src/configs/${CONFIGURATION_TYPE}.sh
fi

if [ -f /opt/app-root/configs/jupyterhub_config.sh ]; then
    . /opt/app-root/configs/jupyterhub_config.sh
fi
