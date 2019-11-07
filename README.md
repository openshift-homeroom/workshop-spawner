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

For all the configurations described below, to override the default image used, pass the `WORKSHOP_IMAGE` template parameter with value referencing the custom image for a specific workshop.

Spawner configurations
----------------------

The spawner supports a number of different configurations, or modes, in which it can be deployed. These are:

* `learning-portal` - Used for workshops, or a permanent interactive learning portal where users are anonymous and may do a workshop at any time. Users are given temporary access as a service account user, with a single temporary project. When a workshop is completed, or the allowed time expires, the service account and project are automatically deleted.

* `hosted-workshop` - Used to run a supervised workshop where each user is provided with separate login credentials for an existing user of the OpenShift cluster in which the workshop is being run, in order to login. Users can perform any action in the cluster that the OpenShift user can do, including being able to create multiple projects, if the cluster user quota configuration permits it.

* `terminal-server` - Similar to the hosted workshop configuration. It defaults to only supplying an interactive terminal in the browser using the workshop terminal base image. If a workshop using the full workshop dashboard base is used with this configuration, no embedded web console is provided.

* `user-workspace` - Similar to the learning portal configuration, but users need to login through Keycloak. Users are given access as a service account user, with a single project. The service account and project are dedicated to the user and will still be present if the user were to leave and come back at a future time. This provides a place where users can do ongoing work, but without needing to allocate users in OpenShift itself.

* `jumpbox-server` - Users login through Keycloak. It defaults to only supplying an interactive terminal in the browser using the workshop terminal base image. The user has no access to the cluster itself to do anything. The terminal would be used to access a separate system.

Deploying the spawner
---------------------

For each spawner configuration there is a separate template. The templates come in `production` and `development` variants. Unless you are working on the spawner, you can ignore the `development` variant of the template.

The format of the command for deploying the spawner using any of the templates is:

```
oc process -f https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/learning-portal-production.json --param SPAWNER_NAMESPACE=`oc project --short` --param CLUSTER_SUBDOMAIN=apps.openshiftcluster.com | oc apply -f -
```

In this case we have used the `learning-portal` template. Replace the name with that for the configuration you want to use.

The `SPAWNER_NAMESPACE` template parameter is to pass in the name of the project the spawner is being deployed into. It should match the current project, or the project name passed in using the `-n` or `--namespace` option if supplied.

The `CLUSTER_SUBDOMAIN` template parameter needs to provide the name of the cluster subdomain under which hostnames created for generated routes reside. You can also supply your own custom subdomain so long as DNS is setup to direct requests under that subdomain to the cluster.

The default name used by the deployment will be the same as the configuration. If you need to override this, use the `WORKSHOP_NAME` template parameter.

If you intend deploying multiple instances of the spawner using the same configuration type, and with the same deployed name, in different projects, you must provide the `NAME_PREFIX` template parameter and pass in a value which when combined with the name of the deployment is unique for the cluster. This is necessary as the deployment will create resources which are global and not contained within the project namespace. If you don't supply `NAME_PREFIX`, the global resource names will clash for the two deployments.

Deleting the deployment
-----------------------

To delete the deployment run the command:

```
oc delete all,serviceaccount,configmap,secret,persistentvolumeclaim,rolebinding,clusterrole,clusterrolebinding,oauthclient -l app=learning-portal
```

Replace the value of the `app` label with that which was actually used for the deployment. This will be a combination of `NAME_PREFIX` and `WORKSHOP_NAME`.

Customizing configuration
-------------------------

Each template provides a range of template parameters that can be supplied to customize the deployment.

For example, to override the default image for the user environment and supply a reference to a custom image for a specific workshop, use the `WORKSHOP_IMAGE` template parameter. You can use the `WORKSHOP_NAME` template parameter to override the name used for the deployment.

```
oc new-app https://raw.githubusercontent.com/openshift-homeroom/workshop-spawner/master/templates/learning-portal-production.json --param SPAWNER_NAMESPACE=`oc project --short` --param WORKSHOP_NAME=lab-workshop-content --param WORKSHOP_IMAGE=quay.io/openshifthomeroom/lab-workshop-content:master
```

Look at the individual template files in the templates directory for the list of parameters they accept.

Deployment scripts
------------------

For an easier way of deploying a workshop for multiple users, check out the repository:

* https://github.com/openshift-homeroom/workshop-scripts

This can be used in combination with the repository for a workshop, to embed deployment scripts into the workshop for deploying it, without needing any knowledge of the specific steps.
