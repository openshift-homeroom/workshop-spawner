FROM jboss/keycloak-openshift:4.0.0.Final

USER root

COPY . /tmp/src

RUN mv /tmp/src/.s2i/bin /tmp/scripts

RUN rm -rf /tmp/src/.git* && \
    chown -R 1001 /tmp/src && \
    chgrp -R 0 /tmp/src && \
    chmod -R g+w /tmp/src

USER 1001

RUN /tmp/scripts/assemble

CMD [ "/tmp/scripts/run" ]
