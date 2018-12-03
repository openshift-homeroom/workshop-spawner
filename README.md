Workshop Terminals
==================

This repository contains software for deploying a containerised user environment in OpenShift, for the purposes of supporting workshops using OpenShift.

The environment created for each user is pre-populated with OpenShift and Kubernetes command line clients, along with development tools for Java, Node.js and Python. Access to the user environment is provided via an interactive terminal delivered to the user via their web browser.

Quick start instructions
------------------------

If you don't want to read about how the environments work, nor how they can be customised to include your own additional content and tools, run:

```
$ oc new-app https://raw.githubusercontent.com/openshift-labs/workshop-terminals/master/templates/production.json
```

This will create a deployment for the ``terminal`` application. Check the output from ``oc new-app`` for the public URL the application can be accessed with, or run the following command to get details of the route.

```
$ oc get route terminal
```

When a user visits the URL for the application, they will be redirected to the login page for the OpenShift cluster. Once the user has logged in, after the  user environment has been created, they will be presented with an interactive shell in their browser.

From the interactive shell, to login to the OpenShift cluster from the command line, use the command:

```
$ oc login
The server uses a certificate signed by an unknown authority.
You can bypass the certificate check, but any data you send to the server could be intercepted by others.
Use insecure connections? (y/n): y

Authentication required for https://172.30.0.1:443 (openshift)
Username: user1
Password:
Login successful.

You have one project on this server: "user1"

Using project "user1".
```

Login using the ``oc login`` command is done against the internal REST API access point for the cluster, using information automatically set within the user environment. It is not necessary to provide the URL for the OpenShift cluster if logging in to the same cluster. If prompted to, you will need to accept the certificate.

The command for deploying the user environments will use pre-built images hosted on the quay.io image registry. The image for the user environment has versions of ``oc`` and ``kubectl`` for multiple OpenShift versions and will automatically use the appropriate version for the OpenShift cluster the user environments are running in.
