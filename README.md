Workshop Terminal/Dashboard Spawner
===================================

This repository contains an application spawner for deploying a containerised user environment in OpenShift, for the purposes of supporting workshops using OpenShift.

The environment created for each user is pre-populated with OpenShift and Kubernetes command line clients, along with development tools for Java, Node.js and Python. Access to the user environment is provided via an interactive terminal delivered to the user via their web browser.

Workshop base images
--------------------

Workshop content and any additional applications required are bundled as an image. The base image for the full workshop environment is:

* https://github.com/openshift-homeroom/workshop-dashboard

The base image if needing only an interactive terminal is:

* https://github.com/openshift-homeroom/workshop-terminal

A workshop image would extend these to add their own content.

For all the configurations described below, to override the default image used, pass the `TERMINAL_IMAGE` template parameter with value referencing the custom image for a specific workshop.

Spawner configurations
----------------------

The spawner supports a number of different configurations, or modes, in which it can be deployed. These are:

* `learning-portal` - Used for workshops, or a permanent interactive learning portal where users are anonymous and may do a workshop at any time. Users are given temporary access as a service account user, with a single temporary project. When a workshop is completed, or the allowed time expires, the service account and project are automatically deleted.

* `hosted-workshop` - Used to run a supervised workshop where each user is provided with separate login credentials for an existing user of the OpenShift cluster in which the workshop is being run, in order to login. Users can perform any action in the cluster that the OpenShift user can do, including being able to create multiple projects, if the cluster user quota configuration permits it.

* `terminal-server` - Similar to the hosted workshop configuration. It defaults to only supplying an interactive terminal in the browser using the workshop terminal base image. If a workshop using the full workshop dashboard base is used with this configuration, no embedded web console is provided.

* `user-workspace` - Similar to the learning portal configuration, but users need to login through Keycloak. Users are given access as a service account user, with a single project. The service account and project are dedicated to the user and will still be present if the user were to leave and come back at a future time. This provides a place where users can do ongoing work, but without needing to allocate users in OpenShift itself.

* `jumpbox-server` - Users login through Keycloak. It defaults to only supplying an interactive terminal in the browser using the workshop terminal base image. The user has no access to the cluster itself to do anything. The terminal would be used to access a separate system.

Learning portal deployment
--------------------------

To use the learning portal configuration you must be a cluster admin. Run:

```
oc new-app https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/learning-portal-production.json --param PROJECT_NAME=`oc project --short`
```

This will create a deployment called `portal`. Check the output from `oc new-app` for the public URL the application can be accessed with, or run `oc get route`.

To delete the deployment, run:

```
oc delete all,serviceaccount,configmap,secret,rolebinding,clusterrole,clusterrolebinding -l app=portal-`oc project --short`
```

Hosted workshop deployment
--------------------------

To use the hosted workshop configuration you must be a cluster admin. Run:

```
oc new-app https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/hosted-workshop-production.json --param PROJECT_NAME=`oc project --short` --param CLUSTER_SUBDOMAIN=apps.openshiftcluster.com
```

Replace `apps.openshiftcluster.com` with the actual sub domain that routes for
applications deployed to the cluster would use.

This will create a deployment called `workshop`. Check the output from `oc new-app` for the public URL the application can be accessed with, or run `oc get route`.

When a user visits the URL for the application, they will be redirected to the login page for the OpenShift cluster.

To delete the deployment, run:

```
oc delete all,serviceaccount,configmap,secret,persistentvolumeclaim,rolebinding,oauthclient -l app=workshop-`oc project --short`
```

Terminal server deployment
--------------------------

To use the terminal server configuration, you must be a cluster admin. Run:

```
oc new-app https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/terminal-server-production.json --param PROJECT_NAME=`oc project --short` --param CLUSTER_SUBDOMAIN=apps.openshiftcluster.com
```

Replace `apps.openshiftcluster.com` with the actual sub domain that routes for
applications deployed to the cluster would use.

This will create a deployment called `terminal`. Check the output from `oc new-app` for the public URL the application can be accessed with, or run `oc get route`.

When a user visits the URL for the application, they will be redirected to the login page for the OpenShift cluster.

To delete the deployment, run:

```
oc delete all,serviceaccount,configmap,secret,persistentvolumeclaim,rolebinding,oauthclient -l app=terminal-`oc project --short`
```

User workspace deployment
-------------------------

To use the user workspace configuration you must be a cluster admin. Run:

```
oc new-app https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/user-workspace-production.json --param PROJECT_NAME=`oc project --short`
```

This will create a deployment called `workspace`. Check the output from `oc new-app` for the public URL the application can be accessed with, or run `oc get route`.

To delete the deployment, run:

```
oc delete all,serviceaccount,configmap,secret,persistentvolumeclaim,rolebinding,clusterrole,clusterrolebinding -l app=workspace-`oc project --short`
```

Jumpbox server deployment
-------------------------

To use the jumpbox server configuration you be any user with access to the project the deployment is being made to. Run:

```
oc new-app https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/jumpbox-server-production.json --param PROJECT_NAME=`oc project --short`
```

This will create a deployment called `jumpbox`. Check the output from `oc new-app` for the public URL the application can be accessed with, or run `oc get route`.

To delete the deployment, run:

```
oc delete all,serviceaccount,configmap,secret,persistentvolumeclaim,rolebinding -l app=jumpbox-`oc project --short`
```

Customizing configuration
-------------------------

Each template provides a range of template parameters that can be supplied to customize the deployment.

For example, to override the default image for the user environment and supply a reference to a custom image for a specific workshop, use the `TERMINAL_IMAGE` template parameter. You can use the `APPLICATION_NAME` template parameter to override the name used for the deployment.

```
oc new-app https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/learning-portal-production.json --param PROJECT_NAME=`oc project --short` --param APPLICATION_NAME=lab-kubernetes-fundamentals --param TERMINAL_IMAGE=quay.io/openshiftlabs/lab-kubernetes-fundamentals:master
```

Look at the individual template files in the templates directory for the list of parameters they accept.
