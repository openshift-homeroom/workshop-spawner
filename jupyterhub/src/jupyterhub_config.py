# This file provides common configuration for the different ways that
# the deployment can run. Configuration specific to the different modes
# will be read from separate files at the end of this configuration
# file.

import os
import json
import string
import yaml
import threading
import time

import requests
import wrapt

from tornado import gen

from kubernetes.client.rest import ApiException
from kubernetes.client.configuration import Configuration
from kubernetes.config.incluster_config import load_incluster_config
from kubernetes.client.api_client import ApiClient

from openshift.dynamic import DynamicClient, Resource
from openshift.dynamic.exceptions import ResourceNotFoundError

# The workshop name and configuration type are passed in through the
# environment. The applicaton name should be the value used for the
# deployment, and more specifically, must match the name of the route.

workshop_name = os.environ.get('WORKSHOP_NAME')

application_name = os.environ.get('APPLICATION_NAME')
    
if not workshop_name:
    workshop_name = 'homeroom'

if not application_name:
    application_name = workshop_name

print('INFO: Workshop name is %r.' % workshop_name)

print('INFO: Application name is %r.' % application_name)

configuration_type = os.environ.get('CONFIGURATION_TYPE', 'hosted-workshop')

print('INFO: Configuration type is %r.' % configuration_type)

homeroom_link = os.environ.get('HOMEROOM_LINK')

print('INFO: Homeroom link is %r.' % homeroom_link)

homeroom_name = os.environ.get('HOMEROOM_NAME')

print('INFO: Homeroom name is %r.' % homeroom_name)

# Work out the service account name and name of the namespace that the
# deployment is in.

service_account_path = '/var/run/secrets/kubernetes.io/serviceaccount'

service_account_name = '%s-spawner' % application_name

print('INFO: Service account name is %r.' % service_account_name)

with open(os.path.join(service_account_path, 'namespace')) as fp:
    namespace = fp.read().strip()

print('INFO: Namespace is %r.' % namespace)

full_service_account_name = 'system:serviceaccount:%s:%s' % (
        namespace, service_account_name) 

print('INFO: Full service account name is %r.' % full_service_account_name)

# Determine the Kubernetes REST API endpoint and cluster information,
# including working out the address of the internal image regstry.

kubernetes_service_host = os.environ['KUBERNETES_SERVICE_HOST']
kubernetes_service_port = os.environ['KUBERNETES_SERVICE_PORT']

kubernetes_server_url = 'https://%s:%s' % (kubernetes_service_host,
        kubernetes_service_port)

kubernetes_server_version_url = '%s/version' % kubernetes_server_url

with requests.Session() as session:
    response = session.get(kubernetes_server_version_url, verify=False)
    kubernetes_server_info = json.loads(response.content.decode('UTF-8'))

image_registry = 'image-registry.openshift-image-registry.svc:5000'

if kubernetes_server_info['major'] == '1':
    if kubernetes_server_info['minor'] in ('10', '10+', '11', '11+'):
        image_registry = 'docker-registry.default.svc:5000'

# Initialise the client for the REST API used doing configuration.
#
# XXX Currently have a workaround here for OpenShift 4.0 beta versions
# which disables verification of the certificate. If don't use this the
# Python openshift/kubernetes clients will fail. We also disable any
# warnings from urllib3 to get rid of the noise in the logs this creates.

load_incluster_config()

import urllib3
urllib3.disable_warnings()
instance = Configuration()
instance.verify_ssl = False
Configuration.set_default(instance)

api_client = DynamicClient(ApiClient())

try:
    image_stream_resource = api_client.resources.get(
         api_version='image.openshift.io/v1', kind='ImageStream')
except ResourceNotFoundError:
    image_stream_resource = None

try:
    route_resource = api_client.resources.get(
         api_version='route.openshift.io/v1', kind='Route')
except ResourceNotFoundError:
    route_resource = None

ingress_resource = api_client.resources.get(
     api_version='extensions/v1beta1', kind='Ingress')

# Create a background thread to dynamically calculate back link to the
# Homeroom workshop picker if no explicit link is provided, but group is.

def watch_for_homeroom():
    global homeroom_link

    while True:
        if route_resource is not None:
            try:
                route = route_resource.get(namespace=namespace, name=homeroom_name)

                scheme = 'http'

                if route.metadata.annotations:
                    if route.metadata.annotations['homeroom/index'] == homeroom_name:
                        if route.tls and route.tls.termination:
                            scheme = 'https'

                        link = '%s://%s' % (scheme, route.spec.host)

                        if link != homeroom_link:
                            print('INFO: Homeroom link set to %s.' % link)
                            homeroom_link = link

            except ApiException as e:
                if e.status != 404:
                    print('ERROR: Error looking up homeroom route. %s' % e)

            except Exception as e:
                print('ERROR: Error looking up homeroom route. %s' % e)

        try:
            ingress = ingress_resource.get(namespace=namespace, name=homeroom_name)

            scheme = 'http'

            if ingress.metadata.annotations:
                if ingress.metadata.annotations['homeroom/index'] == homeroom_name:
                    if ingress.tls:
                        scheme = 'https'

                    link = '%s://%s' % (scheme, ingress.spec.rules[0].host)

                    if link != homeroom_link:
                        print('INFO: Homeroom link set to %s.' % link)
                        homeroom_link = link

        except ApiException as e:
            if e.status != 404:
                print('ERROR: Error looking up homeroom ingress. %s' % e)

        except Exception as e:
            print('ERROR: Error looking up homeroom ingress. %s' % e)

        time.sleep(15)

if not homeroom_link and homeroom_name:
    thread = threading.Thread(target=watch_for_homeroom)
    thread.daemon = True
    thread.start()

# Workaround bug in minishift where a service cannot be contacted from a
# pod which backs the service. For further details see the minishift issue
# https://github.com/minishift/minishift/issues/2400.
#
# What these workarounds do is monkey patch the JupyterHub proxy client
# API code, and the code for creating the environment for local service
# processes, and when it sees something which uses the service name as
# the target in a URL, it replaces it with localhost. These work because
# the proxy/service processes are in the same pod. It is not possible to
# change hub_connect_ip to localhost because that is passed to other
# pods which need to contact back to JupyterHub, and so it must be left
# as the service name.

@wrapt.patch_function_wrapper('jupyterhub.proxy', 'ConfigurableHTTPProxy.add_route')
def _wrapper_add_route(wrapped, instance, args, kwargs):
    def _extract_args(routespec, target, data, *_args, **_kwargs):
        return (routespec, target, data, _args, _kwargs)

    routespec, target, data, _args, _kwargs = _extract_args(*args, **kwargs)

    old = 'http://%s:%s' % (c.JupyterHub.hub_connect_ip, c.JupyterHub.hub_port)
    new = 'http://127.0.0.1:%s' % c.JupyterHub.hub_port

    if target.startswith(old):
        target = target.replace(old, new)

    return wrapped(routespec, target, data, *_args, **_kwargs)

@wrapt.patch_function_wrapper('jupyterhub.spawner', 'LocalProcessSpawner.get_env')
def _wrapper_get_env(wrapped, instance, args, kwargs):
    env = wrapped(*args, **kwargs)

    target = env.get('JUPYTERHUB_API_URL')

    old = 'http://%s:%s' % (c.JupyterHub.hub_connect_ip, c.JupyterHub.hub_port)
    new = 'http://127.0.0.1:%s' % c.JupyterHub.hub_port

    if target and target.startswith(old):
        target = target.replace(old, new)
        env['JUPYTERHUB_API_URL'] = target

    return env

# Define all the defaults for the JupyterHub instance for our setup.

c.JupyterHub.port = 8080

c.JupyterHub.hub_ip = '0.0.0.0'
c.JupyterHub.hub_port = 8081

c.JupyterHub.hub_connect_ip = '%s-spawner' % application_name

c.ConfigurableHTTPProxy.api_url = 'http://127.0.0.1:8082'

c.Spawner.start_timeout = 180
c.Spawner.http_timeout = 60

c.KubeSpawner.port = 10080

c.KubeSpawner.common_labels = {
    'app': '%s' % application_name
}

c.KubeSpawner.extra_labels = {
    'spawner': configuration_type,
    'class': 'session',
    'user': '{username}'
}

c.KubeSpawner.uid = os.getuid()
c.KubeSpawner.fs_gid = os.getuid()

c.KubeSpawner.extra_annotations = {
    "alpha.image.policy.openshift.io/resolve-names": "*"
}

c.KubeSpawner.cmd = ['start-singleuser.sh']

c.KubeSpawner.pod_name_template = '%s-user-{username}' % application_name

c.JupyterHub.admin_access = False

if os.environ.get('JUPYTERHUB_COOKIE_SECRET'):
    c.JupyterHub.cookie_secret = os.environ[
            'JUPYTERHUB_COOKIE_SECRET'].encode('UTF-8')
else:
    c.JupyterHub.cookie_secret_file = '/opt/app-root/data/cookie_secret'

c.JupyterHub.db_url = '/opt/app-root/data/database.sqlite'

c.JupyterHub.authenticator_class = 'tmpauthenticator.TmpAuthenticator'

c.JupyterHub.spawner_class = 'kubespawner.KubeSpawner'

c.JupyterHub.logo_file = '/opt/app-root/src/images/HomeroomIcon.png'

c.Spawner.environment = dict()

c.JupyterHub.services = []

c.KubeSpawner.init_containers = []

c.KubeSpawner.extra_containers = []

c.JupyterHub.extra_handlers = []

# Determine amount of memory to allocate for workshop environment.

def convert_size_to_bytes(size):
    multipliers = {
        'k': 1000,
        'm': 1000**2,
        'g': 1000**3,
        't': 1000**4,
        'ki': 1024,
        'mi': 1024**2,
        'gi': 1024**3,
        'ti': 1024**4,
    }

    size = str(size)

    for suffix in multipliers:
        if size.lower().endswith(suffix):
            return int(size[0:-len(suffix)]) * multipliers[suffix]
    else:
        if size.lower().endswith('b'):
            return int(size[0:-1])

    try:
        return int(size)
    except ValueError:
        raise RuntimeError('"%s" is not a valid memory specification. Must be an integer or a string with suffix K, M, G, T, Ki, Mi, Gi or Ti.' % size)

c.Spawner.mem_limit = convert_size_to_bytes(
        os.environ.get('WORKSHOP_MEMORY', '512Mi'))

# Override the image details with that for the terminal or dashboard
# image being used. The default is to assume that a image stream with
# the same name as the application name is being used. The call to the
# function resolve_image_name() is to try and resolve to image registry
# when using image stream. This is to workaround issue that many
# clusters do not have image policy controller configured correctly.
#
# Note that we set the policy that images will always be pulled to the
# node each time when the image name is not explicitly provided. This is
# so that during development, changes to the terminal image will always
# be picked up. Someone developing a new image need only update the
# 'latest' tag on the image using 'oc tag'. 
#
# Check for TERMINAL_IMAGE is for backward compatibility. Should use
# WORKSHOP_IMAGE now.

workshop_image = os.environ.get('WORKSHOP_IMAGE')

if not workshop_image:
    workshop_image = os.environ.get('TERMINAL_IMAGE')

if not workshop_image:
    c.KubeSpawner.image_pull_policy = 'Always'
    workshop_image = '%s-session:latest' % application_name

def resolve_image_name(name):
    # If no image stream resource we are on plain Kubernetes.

    if image_stream_resource is None:
        return name

    # If the image name contains a slash, we assume it is already
    # referring to an image on some image registry. Even if it does
    # not contain a slash, it may still be hosted on docker.io.

    if name.find('/') != -1:
        return name

    # Separate actual source image name and tag for the image from the
    # name. If the tag is not supplied, default to 'latest'.

    parts = name.split(':', 1)

    if len(parts) == 1:
        source_image, tag = parts, 'latest'
    else:
        source_image, tag = parts

    # See if there is an image stream in the current project with the
    # target name.

    try:
        image_stream = image_stream_resource.get(namespace=namespace,
                name=source_image)

    except ApiException as e:
        if e.status not in (403, 404):
            raise

        return name

    # If we get here then the image stream exists with the target name.
    # We need to determine if the tag exists. If it does exist, we
    # extract out the full name of the image including the reference
    # to the image registry it is hosted on.

    if image_stream.status.tags:
        for entry in image_stream.status.tags:
            if entry.tag == tag:
                registry_image = image_stream.status.dockerImageRepository
                if registry_image:
                    return '%s:%s' % (registry_image, tag)

    # Use original value if can't find a matching tag.

    return name

c.KubeSpawner.image = resolve_image_name(workshop_image)

# Work out hostname for the exposed route of the JupyterHub server. This
# is tricky as we need to use the REST API to query it. This is used
# when needing to do OAuth.

public_hostname = os.environ.get('PUBLIC_HOSTNAME')
public_protocol = os.environ.get('PUBLIC_PROTOCOL')

route_name = '%s-spawner' % application_name

if not public_hostname:
    if route_resource is not None:
        routes = route_resource.get(namespace=namespace)

        for route in routes.items:
            if route.metadata.name == route_name:
                if not public_protocol:
                    public_protocol = route.spec.tls and 'https' or 'http'
                public_hostname = route.spec.host
                break

    if not public_hostname:
        ingresses = ingress_resource.get(namespace=namespace)

        for ingresses in ingresses.items:
            if ingresses.metadata.name == route_name:
                if not public_protocol:
                    public_protocol = ingresses.spec.tls and 'https' or 'http'
                public_hostname = ingresses.spec.rules[0].host
                break

        if not public_hostname:
            raise RuntimeError('Cannot calculate external host name for the spawner.')

c.Spawner.environment['JUPYTERHUB_ROUTE'] = '%s://%s' % (public_protocol, public_hostname)

# Work out the subdomain under which applications hosted in the cluster
# are hosted. Calculate this from the route for the spawner route if
# not supplied explicitly.

cluster_subdomain = os.environ.get('CLUSTER_SUBDOMAIN')

if not cluster_subdomain:
    cluster_subdomain = '.'.join(public_hostname.split('.')[1:])

c.Spawner.environment['CLUSTER_SUBDOMAIN'] = cluster_subdomain

# The terminal image will normally work out what versions of OpenShift
# and Kubernetes command line tools should be used, based on the version
# of OpenShift which is being used. Allow these to be overridden if
# necessary.

if os.environ.get('OC_VERSION'):
    c.Spawner.environment['OC_VERSION'] = os.environ.get('OC_VERSION')
if os.environ.get('ODO_VERSION'):
    c.Spawner.environment['ODO_VERSION'] = os.environ.get('ODO_VERSION')
if os.environ.get('KUBECTL_VERSION'):
    c.Spawner.environment['KUBECTL_VERSION'] = os.environ.get('KUBECTL_VERSION')

# Common functions for creating projects, injecting resources etc.

namespace_resource = api_client.resources.get(
     api_version='v1', kind='Namespace')

service_account_resource = api_client.resources.get(
     api_version='v1', kind='ServiceAccount')

secret_resource = api_client.resources.get(
     api_version='v1', kind='Secret')

cluster_role_resource = api_client.resources.get(
     api_version='rbac.authorization.k8s.io/v1', kind='ClusterRole')

role_binding_resource = api_client.resources.get(
     api_version='rbac.authorization.k8s.io/v1', kind='RoleBinding')

limit_range_resource = api_client.resources.get(
     api_version='v1', kind='LimitRange')

resource_quota_resource = api_client.resources.get(
     api_version='v1', kind='ResourceQuota')

service_resource = api_client.resources.get(
     api_version='v1', kind='Service')

namespace_template = string.Template("""
{
    "kind": "Namespace",
    "apiVersion": "v1",
    "metadata": {
        "name": "${name}",
        "labels": {
            "app": "${application_name}",
            "spawner": "${configuration}",
            "class": "session",
            "user": "${username}"
        },
        "annotations": {
            "spawner/requestor": "${requestor}",
            "spawner/namespace": "${namespace}",
            "spawner/deployment": "${deployment}",
            "spawner/account": "${account}",
            "spawner/session": "${session}"
        },
        "ownerReferences": [
            {
                "apiVersion": "v1",
                "kind": "ClusterRole",
                "blockOwnerDeletion": false,
                "controller": true,
                "name": "${owner}",
                "uid": "${uid}"
            }
        ]
    }
}
""")

service_account_template = string.Template("""
{
    "kind": "ServiceAccount",
    "apiVersion": "v1",
    "metadata": {
        "name": "${name}",
        "labels": {
            "app": "${application_name}",
            "spawner": "${configuration}",
            "class": "session",
            "user": "${username}"
        }
    }
}
""")

role_binding_template = string.Template("""
{
    "kind": "RoleBinding",
    "apiVersion": "rbac.authorization.k8s.io/v1",
    "metadata": {
        "name": "${name}-${tag}",
        "labels": {
            "app": "${application_name}",
            "spawner": "${configuration}",
            "class": "session",
            "user": "${username}"
        }
    },
    "subjects": [
        {
            "kind": "ServiceAccount",
            "namespace": "${namespace}",
            "name": "${name}"
        }
    ],
    "roleRef": {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "ClusterRole",
        "name": "${role}"
    }
}
""")

resource_budget_mapping = {
    "small": {
        "resource-limits" : {
            "kind": "LimitRange",
            "apiVersion": "v1",
            "metadata": {
                "name": "resource-limits",
                "annotations": {
                    "resource-budget": "small"
                }
            },
            "spec": {
                "limits": [
                    {
                        "type": "Pod",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "1",
                            "memory": "1Gi"
                        }
                    },
                    {
                        "type": "Container",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "1",
                            "memory": "1Gi"
                        },
                        "default": {
                            "cpu": "250m",
                            "memory": "256Mi"
                        },
                        "defaultRequest": {
                            "cpu": "50m",
                            "memory": "128Mi"
                        }
                    },
                    {
                        "type": "PersistentVolumeClaim",
                        "min": {
                            "storage": "1Gi"
                        },
                        "max": {
                            "storage": "1Gi"
                        }
                    }
                ]
            }
        },
        "compute-resources" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources",
                "annotations": {
                    "resource-budget": "small"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "1",
                    "limits.memory": "1Gi"
                },
                "scopes": [
                    "NotTerminating"
                ]
            }
        },
        "compute-resources-timebound" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources-timebound",
                "annotations": {
                    "resource-budget": "small"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "1",
                    "limits.memory": "1Gi"
                },
                "scopes": [
                    "Terminating"
                ]
            }
        },
        "object-counts" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "object-counts",
                "annotations": {
                    "resource-budget": "small"
                }
            },
            "spec": {
                "hard": {
                    "persistentvolumeclaims": "3",
                    "replicationcontrollers": "10",
                    "secrets": "20",
                    "services": "5"
                }
            }
        },
    },
    "medium": {
        "resource-limits" : {
            "kind": "LimitRange",
            "apiVersion": "v1",
            "metadata": {
                "name": "resource-limits",
                "annotations": {
                    "resource-budget": "medium"
                }
            },
            "spec": {
                "limits": [
                    {
                        "type": "Pod",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "2",
                            "memory": "2Gi"
                        }
                    },
                    {
                        "type": "Container",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "2",
                            "memory": "2Gi"
                        },
                        "default": {
                            "cpu": "500m",
                            "memory": "512Mi"
                        },
                        "defaultRequest": {
                            "cpu": "50m",
                            "memory": "128Mi"
                        }
                    },
                    {
                        "type": "PersistentVolumeClaim",
                        "min": {
                            "storage": "1Gi"
                        },
                        "max": {
                            "storage": "5Gi"
                        }
                    }
                ]
            }
        },
        "compute-resources" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources",
                "annotations": {
                    "resource-budget": "medium"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "2",
                    "limits.memory": "2Gi"
                },
                "scopes": [
                    "NotTerminating"
                ]
            }
        },
        "compute-resources-timebound" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources-timebound",
                "annotations": {
                    "resource-budget": "medium"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "2",
                    "limits.memory": "2Gi"
                },
                "scopes": [
                    "Terminating"
                ]
            }
        },
        "object-counts" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "object-counts",
                "annotations": {
                    "resource-budget": "medium"
                }
            },
            "spec": {
                "hard": {
                    "persistentvolumeclaims": "6",
                    "replicationcontrollers": "15",
                    "secrets": "25",
                    "services": "10"
                }
            }
        },
    },
    "large": {
        "resource-limits" : {
            "kind": "LimitRange",
            "apiVersion": "v1",
            "metadata": {
                "name": "resource-limits",
                "annotations": {
                    "resource-budget": "large"
                }
            },
            "spec": {
                "limits": [
                    {
                        "type": "Pod",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "4",
                            "memory": "4Gi"
                        }
                    },
                    {
                        "type": "Container",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "4",
                            "memory": "4Gi"
                        },
                        "default": {
                            "cpu": "500m",
                            "memory": "1Gi"
                        },
                        "defaultRequest": {
                            "cpu": "50m",
                            "memory": "128Mi"
                        }
                    },
                    {
                        "type": "PersistentVolumeClaim",
                        "min": {
                            "storage": "1Gi"
                        },
                        "max": {
                            "storage": "10Gi"
                        }
                    }
                ]
            }
        },
        "compute-resources" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources",
                "annotations": {
                    "resource-budget": "large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "4",
                    "limits.memory": "4Gi"
                },
                "scopes": [
                    "NotTerminating"
                ]
            }
        },
        "compute-resources-timebound" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources-timebound",
                "annotations": {
                    "resource-budget": "large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "4",
                    "limits.memory": "4Gi"
                },
                "scopes": [
                    "Terminating"
                ]
            }
        },
        "object-counts" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "object-counts",
                "annotations": {
                    "resource-budget": "large"
                }
            },
            "spec": {
                "hard": {
                    "persistentvolumeclaims": "12",
                    "replicationcontrollers": "25",
                    "secrets": "35",
                    "services": "20"
                }
            }
        }
    },
    "x-large": {
        "resource-limits" : {
            "kind": "LimitRange",
            "apiVersion": "v1",
            "metadata": {
                "name": "resource-limits",
                "annotations": {
                    "resource-budget": "x-large"
                }
            },
            "spec": {
                "limits": [
                    {
                        "type": "Pod",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "8",
                            "memory": "8Gi"
                        }
                    },
                    {
                        "type": "Container",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "8",
                            "memory": "8Gi"
                        },
                        "default": {
                            "cpu": "500m",
                            "memory": "2Gi"
                        },
                        "defaultRequest": {
                            "cpu": "50m",
                            "memory": "128Mi"
                        }
                    },
                    {
                        "type": "PersistentVolumeClaim",
                        "min": {
                            "storage": "1Gi"
                        },
                        "max": {
                            "storage": "20Gi"
                        }
                    }
                ]
            }
        },
        "compute-resources" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources",
                "annotations": {
                    "resource-budget": "x-large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "8",
                    "limits.memory": "8Gi"
                },
                "scopes": [
                    "NotTerminating"
                ]
            }
        },
        "compute-resources-timebound" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources-timebound",
                "annotations": {
                    "resource-budget": "x-large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "8",
                    "limits.memory": "8Gi"
                },
                "scopes": [
                    "Terminating"
                ]
            }
        },
        "object-counts" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "object-counts",
                "annotations": {
                    "resource-budget": "x-large"
                }
            },
            "spec": {
                "hard": {
                    "persistentvolumeclaims": "18",
                    "replicationcontrollers": "35",
                    "secrets": "45",
                    "services": "30"
                }
            }
        }
    },
    "xx-large": {
        "resource-limits" : {
            "kind": "LimitRange",
            "apiVersion": "v1",
            "metadata": {
                "name": "resource-limits",
                "annotations": {
                    "resource-budget": "xx-large"
                }
            },
            "spec": {
                "limits": [
                    {
                        "type": "Pod",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "12",
                            "memory": "12Gi"
                        }
                    },
                    {
                        "type": "Container",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "12",
                            "memory": "12Gi"
                        },
                        "default": {
                            "cpu": "500m",
                            "memory": "2Gi"
                        },
                        "defaultRequest": {
                            "cpu": "50m",
                            "memory": "128Mi"
                        }
                    },
                    {
                        "type": "PersistentVolumeClaim",
                        "min": {
                            "storage": "1Gi"
                        },
                        "max": {
                            "storage": "20Gi"
                        }
                    }
                ]
            }
        },
        "compute-resources" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources",
                "annotations": {
                    "resource-budget": "xx-large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "12",
                    "limits.memory": "12Gi"
                },
                "scopes": [
                    "NotTerminating"
                ]
            }
        },
        "compute-resources-timebound" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources-timebound",
                "annotations": {
                    "resource-budget": "xx-large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "12",
                    "limits.memory": "12Gi"
                },
                "scopes": [
                    "Terminating"
                ]
            }
        },
        "object-counts" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "object-counts",
                "annotations": {
                    "resource-budget": "xx-large"
                }
            },
            "spec": {
                "hard": {
                    "persistentvolumeclaims": "24",
                    "replicationcontrollers": "45",
                    "secrets": "55",
                    "services": "40"
                }
            }
        }
    },
    "xxx-large": {
        "resource-limits" : {
            "kind": "LimitRange",
            "apiVersion": "v1",
            "metadata": {
                "name": "resource-limits",
                "annotations": {
                    "resource-budget": "xxx-large"
                }
            },
            "spec": {
                "limits": [
                    {
                        "type": "Pod",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "16",
                            "memory": "16Gi"
                        }
                    },
                    {
                        "type": "Container",
                        "min": {
                            "cpu": "50m",
                            "memory": "32Mi"
                        },
                        "max": {
                            "cpu": "16",
                            "memory": "16Gi"
                        },
                        "default": {
                            "cpu": "500m",
                            "memory": "2Gi"
                        },
                        "defaultRequest": {
                            "cpu": "50m",
                            "memory": "128Mi"
                        }
                    },
                    {
                        "type": "PersistentVolumeClaim",
                        "min": {
                            "storage": "1Gi"
                        },
                        "max": {
                            "storage": "20Gi"
                        }
                    }
                ]
            }
        },
        "compute-resources" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources",
                "annotations": {
                    "resource-budget": "xxx-large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "16",
                    "limits.memory": "16Gi"
                },
                "scopes": [
                    "NotTerminating"
                ]
            }
        },
        "compute-resources-timebound" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "compute-resources-timebound",
                "annotations": {
                    "resource-budget": "xxx-large"
                }
            },
            "spec": {
                "hard": {
                    "limits.cpu": "16",
                    "limits.memory": "16Gi"
                },
                "scopes": [
                    "Terminating"
                ]
            }
        },
        "object-counts" : {
            "kind": "ResourceQuota",
            "apiVersion": "v1",
            "metadata": {
                "name": "object-counts",
                "annotations": {
                    "resource-budget": "xxx-large"
                }
            },
            "spec": {
                "hard": {
                    "persistentvolumeclaims": "30",
                    "replicationcontrollers": "55",
                    "secrets": "65",
                    "services": "50"
                }
            }
        }
    }
}

service_template = string.Template("""
{
    "kind": "Service",
    "apiVersion": "v1",
    "metadata": {
        "name": "${name}",
        "labels": {
            "app": "${application_name}",
            "spawner": "${configuration}",
            "class": "session",
            "user": "${username}"
        },
        "ownerReferences": [
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "blockOwnerDeletion": false,
                "controller": true,
                "name": "${name}",
                "uid": "${uid}"
            }
        ]
    },
    "spec": {
        "type": "ClusterIP",
        "selector": {
            "app": "${application_name}",
            "spawner": "${configuration}",
            "user": "${username}"
        },
        "ports": []
    }
}
""")

route_template = string.Template("""
{
    "apiVersion": "route.openshift.io/v1",
    "kind": "Route",
    "metadata": {
        "name": "${name}-${port}",
        "labels": {
            "app": "${application_name}",
            "spawner": "${configuration}",
            "class": "session",
            "user": "${username}",
            "port": "${port}"
        },
        "ownerReferences": [
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "blockOwnerDeletion": false,
                "controller": true,
                "name": "${name}",
                "uid": "${uid}"
            }
        ]
    },
    "spec": {
        "host": "${host}",
        "port": {
            "targetPort": "${port}-tcp"
        },
        "to": {
            "kind": "Service",
            "name": "${name}",
            "weight": 100
        }
    }
}
""")

@gen.coroutine
def create_service_account(spawner, pod):
    short_name = spawner.user.name
    user_account_name = '%s-%s' % (application_name, short_name)

    owner_uid = None

    print('INFO: Create service account "%s".' % user_account_name)

    while True:
        try:
            text = service_account_template.safe_substitute(
                    configuration=configuration_type, namespace=namespace,
                    name=user_account_name, application_name=application_name,
                    username=short_name)
            body = json.loads(text)

            service_account_object = service_account_resource.create(
                    namespace=namespace, body=body)

            owner_uid = service_account_object.metadata.uid

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating service account. %s' % e)
                raise

            else:
                print('WARNING: Service account %s exists.' % user_account_name)
                break

        except Exception as e:
            print('ERROR: Error creating service account. %s' % e)
            raise

        else:
            break

    # If we didn't create a service account object as one already existed,
    # we need to query the existing one to get the uid to use as owner.

    if owner_uid is None:
        try:
            service_account_object = service_account_resource.get(
                    namespace=namespace, name=user_account_name)

            owner_uid = service_account_object.metadata.uid

        except Exception as e:
            print('ERROR: Error getting service account. %s' % e)
            raise

    print('INFO: Service account id is %s.' % owner_uid)

    return owner_uid

@gen.coroutine
def create_project_namespace(spawner, pod, project_name):
    short_name = spawner.user.name
    user_account_name = '%s-%s' % (application_name, short_name)

    try:
        text = namespace_template.safe_substitute(
                configuration=configuration_type, name=project_name,
                application_name=application_name,
                requestor=full_service_account_name, namespace=namespace,
                deployment=application_name, account=user_account_name,
                session=pod.metadata.name, owner=project_owner.metadata.name,
                uid=project_owner.metadata.uid, username=short_name)
        body = json.loads(text)

        namespace_resource.create(body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating project. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating project. %s' % e)
        raise

@gen.coroutine
def setup_project_namespace(spawner, pod, project_name, role, budget):
    short_name = spawner.user.name
    user_account_name = '%s-%s' % (application_name, short_name)

    # Wait for project namespace to exist before continuing.

    for _ in range(30):
        try:
            project = namespace_resource.get(name=project_name)

        except ApiException as e:
            if e.status == 404:
                yield gen.sleep(0.1)
                continue

            print('ERROR: Error querying project. %s' % e)
            raise

        else:
            break

    else:
        # If can't verify project created, carry on anyway.

        print('ERROR: Could not verify project creation. %s' % project_name)

        raise Exception('Could not verify project creation. %s' % project_name)

    project_uid = project.metadata.uid

    # Create role binding in the project so the spawner service account can
    # delete project when done. Will fail if the project hasn't actually
    # been created yet.

    try:
        text = role_binding_template.safe_substitute(
                configuration=configuration_type, namespace=namespace,
                name=service_account_name, tag='admin', role='admin',
                application_name=application_name, username=short_name)
        body = json.loads(text)

        role_binding_resource.create(namespace=project_name, body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating role binding for spawner. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating rolebinding for spawner. %s' % e)
        raise

    # Create role binding in the project so the users service account
    # can create resources in it.

    try:
        text = role_binding_template.safe_substitute(
                configuration=configuration_type, namespace=namespace,
                name=user_account_name, tag=role, role=role,
                application_name=application_name, username=short_name)
        body = json.loads(text)

        role_binding_resource.create(namespace=project_name, body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating role binding for user. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating rolebinding for user. %s' % e)
        raise

    # Create role binding in the project so the users service account
    # can perform additional actions declared through additional policy
    # rules for a specific workshop session.

    try:
        text = role_binding_template.safe_substitute(
                configuration=configuration_type, namespace=namespace,
                name=user_account_name, tag='session-rules',
                role=application_name+'-session-rules',
                application_name=application_name, username=short_name)
        body = json.loads(text)

        role_binding_resource.create(namespace=project_name, body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating role binding for extras. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating rolebinding for extras. %s' % e)
        raise

    # Determine what project namespace resources need to be used.

    if budget != 'unlimited':
        if budget not in resource_budget_mapping:
            budget = 'default'
        elif not resource_budget_mapping[budget]:
            budget = 'default'

    if budget not in ('default', 'unlimited'):
        budget_item = resource_budget_mapping[budget]

        resource_limits_definition = budget_item['resource-limits']
        compute_resources_definition = budget_item['compute-resources']
        compute_resources_timebound_definition = budget_item['compute-resources-timebound']
        object_counts_definition = budget_item['object-counts']

    # Delete any limit ranges applied to the project that may conflict
    # with the limit range being applied. For the case of unlimited, we
    # delete any being applied but don't replace it.

    if budget != 'default':
        try:
            limit_ranges = limit_range_resource.get(
                        namespace=project_name)

        except ApiException as e:
            print('ERROR: Error querying limit ranges. %s' % e)
            raise

        for limit_range in limit_ranges.items:
            try:
                limit_range_resource.delete(namespace=project_name,
                    name=limit_range.metadata.name)

            except ApiException as e:
                print('ERROR: Error deleting limit range. %s' % e)
                raise

    # Create limit ranges for the project namespace so any deployments
    # will have default memory/cpu min and max values.

    if budget not in ('default', 'unlimited'):
        try:
            body = resource_limits_definition

            limit_range_resource.create(namespace=project_name, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating limit range. %s' % e)
                raise

    # Delete any resource quotas applied to the project namespace that
    # may conflict with the resource quotas being applied.

    if budget != 'default':
        try:
            resource_quotas = resource_quota_resource.get(namespace=project_name)

        except ApiException as e:
            print('ERROR: Error querying resource quotas. %s' % e)
            raise

        for resource_quota in resource_quotas.items:
            try:
                resource_quota_resource.delete(namespace=project_name,
                    name=resource_quota.metadata.name)

            except ApiException as e:
                print('ERROR: Error deleting resource quota. %s' % e)
                raise

    # Create resource quotas for the project so there is a maximum for
    # what resources can be used.

    if budget not in ('default', 'unlimited'):
        try:
            body = compute_resources_definition

            resource_quota_resource.create(namespace=project_name, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating compute resources quota. %s' % e)
                raise

        try:
            body = compute_resources_timebound_definition

            resource_quota_resource.create(namespace=project_name, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating compute resources timebound quota. %s' % e)
                raise

        try:
            body = object_counts_definition

            resource_quota_resource.create(namespace=project_name, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating object counts quota. %s' % e)
                raise

    # Return the project UID for later use as owner UID if needed.

    return project_uid

extra_resources = {}
extra_resources_loader = None

if os.path.exists('/opt/app-root/resources/extra_resources.yaml'):
    with open('/opt/app-root/resources/extra_resources.yaml') as fp:
        extra_resources = fp.read().strip()
        extra_resources_loader = yaml.safe_load

if os.path.exists('/opt/app-root/resources/extra_resources.json'):
    with open('/opt/app-root/resources/extra_resources.json') as fp:
        extra_resources = fp.read().strip()
        extra_resources_loader = json.loads

def _namespaced_resources():
    api_groups = api_client.resources.parse_api_groups()

    for api in api_groups.values():
        for domain, items in api.items():
            for version, group in items.items():
                try:
                    for kind in group.resources:
                        if domain:
                            version = '%s/%s' % (domain, version)
                        resource = api_client.resources.get(api_version=version, kind=kind)
                        if type(resource) == Resource and resource.namespaced:
                            yield (version, resource.kind)
                except Exception:
                    pass

namespaced_resources = set(_namespaced_resources())

@gen.coroutine
def create_extra_resources(spawner, pod, project_name, owner_uid,
        user_account_name, short_name):

    if not extra_resources:
        return

    template = string.Template(extra_resources)
    text = template.safe_substitute(spawner_namespace=namespace,
            project_namespace=project_name, image_registry=image_registry,
            service_account=user_account_name, username=short_name,
            application_name=application_name)

    data = extra_resources_loader(text)

    if isinstance(data, dict) and data.get('kind') == 'List':
        data = data['items']

    for body in data:
        try:
            kind = body['kind']
            api_version = body['apiVersion']

            if not (api_version, kind) in namespaced_resources:
                body['metadata']['ownerReferences'] = [dict(
                    apiVersion='v1', kind='Namespace', blockOwnerDeletion=False,
                    controller=True, name=project_name, uid=owner_uid)]

            if kind.lower() == 'namespace':
                annotations = body['metadata'].setdefault('annotations', {})

                annotations['spawner/requestor'] = full_service_account_name
                annotations['spawner/namespace'] = namespace
                annotations['spawner/deployment'] = application_name
                annotations['spawner/account'] = user_account_name
                annotations['spawner/session'] = pod.metadata.name

            resource = api_client.resources.get(api_version=api_version, kind=kind)

            target_namespace = body['metadata'].get('namespace', project_name)

            resource.create(namespace=target_namespace, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating resource %s. %s' % (body, e))
                raise

            else:
                print('WARNING: Resource already exists %s.' % body)

        except Exception as e:
            print('ERROR: Error creating resource %s. %s' % (body, e))
            raise

        if kind.lower() == 'namespace':
            annotations = body['metadata'].get('annotations', {})
            role = annotations.get('session/role', 'admin')

            default_budget = os.environ.get('RESOURCE_BUDGET', 'default')
            budget = annotations.get('session/budget', default_budget)

            yield setup_project_namespace(spawner, pod,
                    body['metadata']['name'], role, budget)

@gen.coroutine
def expose_service_ports(spawner, pod, owner_uid):
    short_name = spawner.user.name
    user_account_name = '%s-%s' % (application_name, short_name)

    # Can't do this for now if deployed to plain Kubernetes.

    if route_resource is None:
        return

    exposed_ports = os.environ.get('EXPOSED_PORTS', '')

    if exposed_ports:
        exposed_ports = exposed_ports.split(',')

        try:
            text = service_template.safe_substitute(
                    configuration=configuration_type, name=user_account_name,
                    application_name=application_name, username=short_name,
                    uid=owner_uid)
            body = json.loads(text)

            for port in exposed_ports:
                body['spec']['ports'].append(dict(name='%s-tcp' % port,
                        protocol="TCP", port=int(port), targetPort=int(port)))

            service_resource.create(namespace=namespace, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating service. %s' % e)
                raise

        except Exception as e:
            print('ERROR: Error creating service. %s' % e)
            raise

        for port in exposed_ports:
            try:
                host = '%s-%s.%s' % (user_account_name, port, cluster_subdomain)
                text = route_template.safe_substitute(configuration=configuration_type,
                        name=user_account_name, application_name=application_name,
                        port='%s' % port, username=short_name, uid=owner_uid, host=host)
                body = json.loads(text)

                route_resource.create(namespace=namespace, body=body)

            except ApiException as e:
                if e.status != 409:
                    print('ERROR: Error creating route. %s' % e)
                    raise

            except Exception as e:
                print('ERROR: Error creating route. %s' % e)
                raise

@gen.coroutine
def wait_on_service_account(user_account_name):
    for _ in range(10):
        try:
            service_account = service_account_resource.get(
                    namespace=namespace, name=user_account_name)

            # Hope that all secrets added at same time and don't have
            # to check names to verify api token secret added.

            if service_account.secrets:
                for item in service_account.secrets:
                    try:
                        secret = secret_resource.get(namespace=namespace,
                                name=item['name'])

                    except Exception as e:
                        print('WARNING: Error fetching secret. %s' % e)
                        yield gen.sleep(0.1)
                        break

                else:
                    break

            else:
                yield gen.sleep(0.1)
                continue

        except Exception as e:
            print('ERROR: Error fetching service account. %s' % e)
            raise

    else:
        # If can't verify after multiple attempts, continue on anyway.

        print('WARNING: Could not verify account. %s' % user_account_name)

# Load configuration corresponding to the configuration type.

c.Spawner.environment['DEPLOYMENT_TYPE'] = 'spawner'
c.Spawner.environment['CONFIGURATION_TYPE'] = configuration_type

config_root = '/opt/app-root/src/configs'
config_file = '%s/%s.py' % (config_root, configuration_type)

if os.path.exists(config_file):
    with open(config_file) as fp:
        exec(compile(fp.read(), config_file, 'exec'), globals())

# Load configuration provided via the environment.

environ_config_file = '/opt/app-root/configs/jupyterhub_config.py'

if os.path.exists(environ_config_file):
    with open(environ_config_file) as fp:
        exec(compile(fp.read(), environ_config_file, 'exec'), globals())
