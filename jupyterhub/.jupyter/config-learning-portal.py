# This file provides configuration specific to the 'learning-portal'
# deployment mode. In this mode, anonymous authentication is used, with
# users being given their own unique service account and project to work
# in. The project and service account will be deleted when the session
# goes idle or the time limit for the session has expired.

# Use an anonymous authenticator. Users will be automatically assigned a
# user name and don't need to provide a password. During the process of
# doing the psuedo authentication, create a service account for them,
# where the name of service account is their user name. The special
# '/restart' URL handler will cause any session to be restarted and they
# will be given a new instance.

import string
import json
import time
import functools
import random

from tornado import gen, web

from jupyterhub.auth import Authenticator
from jupyterhub.handlers import BaseHandler
from jupyterhub.utils import url_path_join

from kubernetes.client.rest import ApiException

service_account_resource = api_client.resources.get(
     api_version='v1', kind='ServiceAccount')

service_account_template = string.Template("""
{
    "kind": "ServiceAccount",
    "apiVersion": "v1",
    "metadata": {
        "name": "${name}",
        "labels": {
            "hub": "${hub}"
        }
    }
}
""")

class AnonymousUser(object):

    def __init__(self, name):
        self.name = name
        self.active = False

@functools.lru_cache(10000)
def get_user_details(name):
    return AnonymousUser(name)

random_userid_chars = 'bcdfghjklmnpqrstvwxyz0123456789'

def generate_random_userid(n=5):
    return ''.join(random.choice(random_userid_chars) for _ in range(n))

class AutoAuthenticateHandler(BaseHandler):

    def initialize(self, force_new_server, process_user):
        super().initialize()
        self.force_new_server = force_new_server
        self.process_user = process_user

    def generate_user(self):
        while True:
            name = generate_random_userid()
            user = get_user_details(name)
            if not user.active:
                user.active = True
                return name

    @gen.coroutine
    def get(self):
        raw_user = self.get_current_user()

        if raw_user:
            if self.force_new_server and raw_user.running:
                # Stop the user's current terminal instance if it is
                # running so that they get a new one. Should hopefully
                # only end up here if have hit the /restart URL path.

                status = yield raw_user.spawner.poll_and_notify()
                if status is None:
                    yield self.stop_single_user(raw_user)

                # Also force a new user name be generated so don't have
                # issues with browser caching web pages for anything
                # want to be able to change for a demo. Only way to do
                # this seems to be to clear the login cookie and force a
                # redirect back to the top of the site, hoping we do not
                # get into a loop.

                self.clear_login_cookie()
                return self.redirect('/')

        else:
            username = self.generate_user()
            raw_user = self.user_from_username(username)
            self.set_login_cookie(raw_user)

        user = yield gen.maybe_future(self.process_user(raw_user, self))

        # Ensure that a service account exists corresponding to the
        # user.
        #
        # XXX Disable this for now and leave until spawning the pod.
        # If do it here and client doesn't support cookies, the redirect
        # loop results in a service account being created each time
        # through the loop.

        # while True:
        #     hub = '%s-%s' % (application_name, namespace)
        #     account_name = '%s-%s' % (hub, user.name)
        #
        #     try:
        #         text = service_account_template.safe_substitute(
        #                 namespace=namespace, name=account_name, hub=hub)
        #         body = json.loads(text)
        #
        #         service_account_resource.create(namespace=namespace, body=body)
        #
        #     except ApiException as e:
        #         if e.status != 409:
        #             print('ERROR: Error creating service account. %s' % e)
        #             raise
        #
        #         else:
        #             break
        #
        #     except Exception as e:
        #         print('ERROR: Error creating service account. %s' % e)
        #         raise
        #
        #     else:
        #         break

        self.redirect(self.get_argument("next", user.url))

class AutoAuthenticator(Authenticator):

    auto_login = True
    login_service = 'auto'

    force_new_server = True

    def process_user(self, user, handler):
        return user

    def get_handlers(self, app):
        extra_settings = {
            'force_new_server': self.force_new_server,
            'process_user': self.process_user
        }
        return [
            ('/login', AutoAuthenticateHandler, extra_settings)
        ]

    def login_url(self, base_url):
        return url_path_join(base_url, 'login')

c.JupyterHub.authenticator_class = AutoAuthenticator

# Override labels on pods so matches label used by the spawner.

c.KubeSpawner.common_labels = {
    'app': '%s-%s' % (application_name, namespace)
}

c.KubeSpawner.extra_labels = {
    'spawner': 'learning-portal',
    'user': '{username}'
}

# Mount config map for user provided environment variables for the
# terminal and workshop.

c.KubeSpawner.volumes = [
    {
        'name': 'envvars',
        'configMap': {
            'name': '%s-env' % application_name,
            'defaultMode': 420
        }
    }
]

c.KubeSpawner.volume_mounts = [
    {
        'name': 'envvars',
        'mountPath': '/opt/workshop/envvars'
    }
]

# Deploy embedded web console as a separate container within the same
# pod as the terminal instance. Currently use latest, but need to tie
# this to the specific OpenShift version once OpenShift 4.0 is released.

console_branding = os.environ.get('CONSOLE_BRANDING', 'openshift')

c.KubeSpawner.extra_containers.extend([
    {
        "name": "console",
        "image": "quay.io/openshift/origin-console:latest",
        "command": [ "/opt/bridge/bin/bridge" ],
        "env": [
            {
                "name": "BRIDGE_K8S_MODE",
                "value": "in-cluster"
            },
            {
                "name": "BRIDGE_LISTEN",
                "value": "http://0.0.0.0:10083"
            },
            {
                "name": "BRIDGE_BASE_ADDRESS",
                "value": "https://%s/" % public_hostname
            },
            {
                "name": "BRIDGE_BASE_PATH",
                "value": "/user/{unescaped_username}/console/"
            },
            {
                "name": "BRIDGE_PUBLIC_DIR",
                "value": "/opt/bridge/static"
            },
            {
                "name": "BRIDGE_USER_AUTH",
                "value": "disabled"
            },
            {
                "name": "BRIDGE_BRANDING",
                "value": console_branding
            }
        ],
        "resources": {
            "limits": {
                "memory": os.environ.get('CONSOLE_MEMORY', '128Mi')
            },
            "requests": {
                "memory": os.environ.get('CONSOLE_MEMORY', '128Mi')
            }
        }
    }
])

c.Spawner.environment['CONSOLE_URL'] = 'http://localhost:10083'

# Pass through for dashboard the URL where should be redirected in order
# to restart a session, with a new instance created with fresh image.

c.Spawner.environment['RESTART_URL'] = '/restart'

# We need to ensure the service account does actually exist, and also
# create a project for the user and a role binding which allows the
# service account to work on that project. They need to be given admin
# access so they can add other users to their project if necessary, or
# grant service accounts in the project access to the project via the
# REST API. The only place to do this is from the hook function for
# modifying the pod specification before it is created.

project_resource = api_client.resources.get(
     api_version='project.openshift.io/v1', kind='Project')

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

route_resource = api_client.resources.get(
     api_version='route.openshift.io/v1', kind='Route')

namespace_template = string.Template("""
{
    "kind": "Namespace",
    "apiVersion": "v1",
    "metadata": {
        "name": "${name}",
        "labels": {
            "app": "${hub}",
            "spawner": "learning-portal"
        },
        "annotations": {
            "spawner/requestor": "${requestor}",
            "spawner/namespace": "${namespace}",
            "spawner/deployment": "${deployment}",
            "spawner/username": "${username}",
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

role_binding_template = string.Template("""
{
    "kind": "RoleBinding",
    "apiVersion": "rbac.authorization.k8s.io/v1",
    "metadata": {
        "name": "${name}-${tag}",
        "labels": {
            "hub": "${hub}"
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
            "hub": "${hub}"
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
            "hub": "${hub}",
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
            "hub": "${hub}",
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

extra_resources = {}

if os.path.exists('/opt/app-root/resources/extra_resources.json'):
    with open('/opt/app-root/resources/extra_resources.json') as fp:
        extra_resources = fp.read().strip()

def create_extra_resources(project_name, project_uid):
    if not extra_resources:
        return

    template = string.Template(extra_resources)
    text = template.safe_substitute(jupyterhub_namespace=namespace,
            project_namespace=project_name)
    data = json.loads(text)

    for body in data['items']:
        try:
            kind = body['kind']
            api_version = body['apiVersion']

            if kind.lower() in ('securitycontextconstraints', 'clusterrolebinding'):
                body['metadata']['ownerReferences'] = [dict(
                    apiVersion='v1', kind='Namespace', blockOwnerDeletion=False,
                    controller=True, name=project_name, uid=project_uid)]

            resource = api_client.resources.get(api_version=api_version, kind=kind)

            resource.create(namespace=project_name, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating resource %s. %s' % (body, e))
                raise

            else:
                print('WARNING: Resource already exists %s.' % body)

        except Exception as e:
            print('ERROR: Error creating resource %s. %s' % (body, e))
            raise

project_owner_name = '%s-%s-spawner' % (application_name, namespace)

try:
    project_owner = cluster_role_resource.get(project_owner_name)

except Exception as e:
    print('ERROR: Cannot get spawner cluster role %s. %s' % (project_owner_name, e))
    raise

@gen.coroutine
def modify_pod_hook(spawner, pod):
    # Create the service account. We know the user name is a UUID, but
    # it is too long to use as is in project name, so we want to shorten.

    hub = '%s-%s' % (application_name, namespace)
    short_name = spawner.user.name
    project_name = '%s-%s' % (hub, short_name)
    user_account_name = '%s-%s' % (hub, short_name)
    hub_account_name = '%s-hub' % hub

    pod.spec.automount_service_account_token = True
    pod.spec.service_account_name = user_account_name

    # Ensure that a service account exists corresponding to the user.
    # Need to do this as it may have been cleaned up if the session had
    # expired and user wasn't logged out in the browser.

    owner_uid = None

    while True:
        try:
            text = service_account_template.safe_substitute(
                    namespace=namespace, name=user_account_name, hub=hub)
            body = json.loads(text)

            service_account_object = service_account_resource.create(
                    namespace=namespace, body=body)

            owner_uid = service_account_object.metadata.uid

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating service account. %s' % e)
                raise

            else:
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

    # If there are any exposed ports defined for the session, create
    # a service object mapping to the pod for the ports, and create
    # routes for each port.

    exposed_ports = os.environ.get('EXPOSED_PORTS', '')

    if exposed_ports:
        exposed_ports = exposed_ports.split(',')

        try:
            text = service_template.safe_substitute(name=user_account_name,
                    hub=hub, username=short_name, uid=owner_uid)
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
                text = route_template.safe_substitute(name=user_account_name,
                        hub=hub, port='%s' % port, username=short_name,
                        uid=owner_uid, host=host)
                body = json.loads(text)

                route_resource.create(namespace=namespace, body=body)

            except ApiException as e:
                if e.status != 409:
                    print('ERROR: Error creating route. %s' % e)
                    raise

            except Exception as e:
                print('ERROR: Error creating route. %s' % e)
                raise

    # Create a project for just this user. Poll to make sure it is
    # created before continue.

    try:
        service_account_name = 'system:serviceaccount:%s:%s-%s-hub' % (
                namespace, application_name, namespace)

        text = namespace_template.safe_substitute(name=project_name,
                hub=hub, requestor=service_account_name, namespace=namespace,
                deployment=application_name, username=user_account_name,
                session=pod.metadata.name, owner=project_owner.metadata.name,
                uid=project_owner.metadata.uid)
        body = json.loads(text)

        namespace_resource.create(body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating project. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating project. %s' % e)
        raise

    for _ in range(30):
        try:
            project = project_resource.get(name=project_name)

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

    # Create role binding in the project so the hub service account
    # can delete project when done. Will fail if the project hasn't
    # actually been created yet.

    try:
        text = role_binding_template.safe_substitute(
                namespace=namespace, name=hub_account_name, tag='admin',
                role='admin', hub=hub)
        body = json.loads(text)

        role_binding_resource.create(namespace=project_name, body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating role binding for hub. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating rolebinding for hub. %s' % e)
        raise

    # Determine what project resources need to be used.

    resource_budget = os.environ.get('RESOURCE_BUDGET', 'default')

    if resource_budget != 'unlimited':
        if resource_budget not in resource_budget_mapping:
            resource_budget = 'default'
        elif not resource_budget_mapping[resource_budget]:
            resource_budget = 'default'

    if resource_budget not in ('default', 'unlimited'):
        resource_budget_item = resource_budget_mapping[resource_budget]

        resource_limits_definition = resource_budget_item['resource-limits']
        compute_resources_definition = resource_budget_item['compute-resources']
        compute_resources_timebound_definition = resource_budget_item['compute-resources-timebound']
        object_counts_definition = resource_budget_item['object-counts']

    # Delete any limit ranges applied to the project that may conflict
    # with the limit range being applied. For the case of unlimited, we
    # delete any being applied but don't replace it.

    if resource_budget != 'default':
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

    # Create limit ranges for the project so any deployments will have
    # default memory/cpu min and max values.

    if resource_budget not in ('default', 'unlimited'):
        try:
            body = resource_limits_definition

            limit_range_resource.create(namespace=project_name, body=body)

        except ApiException as e:
            if e.status != 409:
                print('ERROR: Error creating limit range. %s' % e)
                raise

    # Delete any resource quotas applied to the project that may conflict
    # with the resource quotas being applied.

    if resource_budget not in ('default', 'unlimited'):
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

    if resource_budget not in ('default', 'unlimited'):
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

    # Create role binding in the project so the users service account
    # can create resources in it. Need to give it 'admin' role and not
    # just 'edit' so that can grant roles to service accounts in the
    # project. This means it could though delete the project itself, and
    # if do that can't create a new one as has no rights to do that.

    try:
        text = role_binding_template.safe_substitute(
                namespace=namespace, name=user_account_name, tag='admin',
                role='admin', hub=hub)
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
                namespace=namespace, name=user_account_name,
                tag='session-rules', role=hub+'-session-rules', hub=hub)
        body = json.loads(text)

        role_binding_resource.create(namespace=project_name, body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating role binding for extras. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating rolebinding for extras. %s' % e)
        raise

    # Create any extra resources in the project required for a workshop.

    create_extra_resources(project_name, project_uid)

    # Before can continue, need to poll looking to see if the secret for
    # the api token has been added to the service account. If don't do
    # this then pod creation will fail immediately. To do this, must get
    # the secrets from the service account and make sure they in turn
    # exist.

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

    # Add environment variable for the project namespace for use in any
    # workshop content.

    pod.spec.containers[0].env.append(
            dict(name='PROJECT_NAMESPACE', value=project_name))

    # Add environment variables for the namespace JupyterHub is running
    # in and its name.

    pod.spec.containers[0].env.append(
            dict(name='JUPYTERHUB_NAMESPACE', value=namespace))
    pod.spec.containers[0].env.append(
            dict(name='JUPYTERHUB_APPLICATION', value=application_name))

    if homeroom_link:
        pod.spec.containers[0].env.append(
                dict(name='HOMEROOM_LINK', value=homeroom_link))

    return pod

c.KubeSpawner.modify_pod_hook = modify_pod_hook

# Setup culling of terminal instances when idle or session expires, as
# well as setup service to clean up service accounts and projects
# related to old sessions. If a server limit is defined, also cap how
# many can be run.

server_limit = os.environ.get('SERVER_LIMIT')

if server_limit:
    c.JupyterHub.active_server_limit = int(server_limit)

idle_timeout = os.environ.get('IDLE_TIMEOUT', '600')
max_session_age = os.environ.get('MAX_SESSION_AGE')

if idle_timeout and int(idle_timeout):
    cull_idle_servers_args = ['cull-idle-servers']

    cull_idle_servers_args.append('--cull-every=60')
    cull_idle_servers_args.append('--timeout=%s' % idle_timeout)
    cull_idle_servers_args.append('--cull-users')

    if max_session_age:
        cull_idle_servers_args.append('--max-age=%s' % max_session_age)

    c.JupyterHub.services.extend([
        {
            'name': 'cull-idle',
            'admin': True,
            'command': cull_idle_servers_args,
        }
    ])

    delete_projects_args = ['/opt/app-root/src/scripts/delete-projects.sh']

    c.JupyterHub.services.extend([
        {
            'name': 'delete-projects',
            'command': delete_projects_args,
            'environment': dict(
                PYTHONUNBUFFERED='1',
                APPLICATION_NAME=application_name,
                KUBERNETES_SERVICE_HOST=os.environ['KUBERNETES_SERVICE_HOST'],
                KUBERNETES_SERVICE_PORT=os.environ['KUBERNETES_SERVICE_PORT']
            ),
        }
    ])

# Redirect handler for sending /restart back to home page for user.

from jupyterhub.handlers import BaseHandler

homeroom_link = os.environ.get('HOMEROOM_LINK')

class RestartRedirectHandler(BaseHandler):

    @web.authenticated
    @gen.coroutine
    def get(self, *args):
        user = self.get_current_user()

        if user.running:
            status = yield user.spawner.poll_and_notify()
            if status is None:
                yield self.stop_single_user(user)
        self.clear_login_cookie()
        self.redirect(homeroom_link or '/hub/spawn')

c.JupyterHub.extra_handlers.extend([
    (r'/restart$', RestartRedirectHandler),
])
