FROM jboss/keycloak:7.0.1

USER root

COPY . /tmp/src

RUN mv /tmp/src/.s2i/bin /tmp/scripts

RUN rm -rf /tmp/src/.git* && \
    chown -R 1000 /tmp/src && \
    chgrp -R 0 /tmp/src && \
    chmod -R g+w /tmp/src

USER 1000

RUN /tmp/scripts/assemble

CMD [ "/tmp/scripts/run" ]
