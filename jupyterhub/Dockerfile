FROM centos/s2i-base-centos7:latest

USER root

# Install required system packages.

RUN HOME=/root && \
    INSTALL_PKGS="sudo rh-python36 rh-python36-python-devel \
        rh-python36-python-setuptools rh-python36-python-pip \
        httpd24 httpd24-httpd-devel httpd24-mod_ssl httpd24-mod_auth_kerb \
        httpd24-mod_ldap httpd24-mod_session" && \
    yum install -y centos-release-scl && \
    yum install -y --setopt=tsflags=nodocs \
        --enablerepo=centosplus $INSTALL_PKGS && \
    rpm -V $INSTALL_PKGS && \
    # Remove centos-logos (httpd dependency) to keep image size smaller.
    rpm -e --nodeps centos-logos && \
    yum -y clean all --enablerepo='*'

# Fixup handling for UNIX accounts.

RUN echo "auth requisite pam_deny.so" >> /etc/pam.d/su && \
    sed -i.bak -e 's/^%wheel/# %wheel/' /etc/sudoers && \
    chmod g+w /etc/passwd

# Install configurable HTTP proxy.

RUN HOME=/root && \
    source scl_source enable $NODEJS_SCL && \
    npm install -g configurable-http-proxy

# Common environment variables.

ENV HOME=/opt/app-root \
    NPM_CONFIG_PREFIX=/opt/app-root \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    PIP_NO_CACHE_DIR=off

# Install application software.

COPY . /opt/app-root/

RUN chown -R 1001:0 /opt/app-root && \
    fix-permissions /opt/app-root

WORKDIR /opt/app-root/src

USER 1001

RUN /opt/app-root/etc/build.sh && \
    fix-permissions /opt/app-root

# Finish environment setup.

ENV BASH_ENV=/opt/app-root/etc/profile \
    ENV=/opt/app-root/etc/profile \
    PROMPT_COMMAND=". /opt/app-root/etc/profile"

ENTRYPOINT [ "/opt/app-root/etc/entrypoint.sh" ]

CMD [ "/opt/app-root/etc/run.sh" ]
