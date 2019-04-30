# This file provides configuration specific to the 'hosted-workshop'
# deployment mode. In this mode authentication for JupyterHub is done
# against the OpenShift cluster using OAuth.

# Work out the public server address for the OpenShift OAuth endpoint.
# Make sure the request is done in a session so the connection is closed
# and later calls against the REST API don't attempt to reuse it. This
# is just to avoid potential for any problems with connection reuse.

import json
import requests

from fnmatch import fnmatch

from tornado import web, gen

kubernetes_service_host = os.environ['KUBERNETES_SERVICE_HOST']
kubernetes_service_port = os.environ['KUBERNETES_SERVICE_PORT']

kubernetes_server_url = 'https://%s:%s' % (kubernetes_service_host,
        kubernetes_service_port)

oauth_metadata_url = '%s/.well-known/oauth-authorization-server' % kubernetes_server_url

with requests.Session() as session:
    response = session.get(oauth_metadata_url, verify=False)
    data = json.loads(response.content.decode('UTF-8'))
    oauth_issuer_address = data['issuer']

# Enable the OpenShift authenticator. The OPENSHIFT_URL environment
# variable must be set before importing the authenticator as it only
# reads it when module is first imported. From OpenShift 4.0 we need
# to supply separate URLs for Kubernetes server and OAuth server.

os.environ['OPENSHIFT_URL'] = oauth_issuer_address

os.environ['OPENSHIFT_REST_API_URL'] = kubernetes_server_url
os.environ['OPENSHIFT_AUTH_API_URL'] = oauth_issuer_address

from oauthenticator.openshift import OpenShiftOAuthenticator
c.JupyterHub.authenticator_class = OpenShiftOAuthenticator

client_id = 'system:serviceaccount:%s:%s' % (namespace, service_account_name)

c.OpenShiftOAuthenticator.client_id = client_id

with open(os.path.join(service_account_path, 'token')) as fp:
    client_secret = fp.read().strip()

c.OpenShiftOAuthenticator.client_secret = client_secret

c.OpenShiftOAuthenticator.oauth_callback_url = (
        'https://%s/hub/oauth_callback' % public_hostname)

c.Authenticator.auto_login = True

# Enable admin access to designated users of the OpenShift cluster.

c.JupyterHub.admin_access = True

c.Authenticator.admin_users = set(os.environ.get('ADMIN_USERS', '').split())

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

# For workshops we provide each user with a persistent volume so they
# don't loose their work. This is mounted on /opt/app-root, so we need
# to copy the contents from the image into the persistent volume the
# first time using an init container.
#
# Note that if a profiles list is used, there must still be a default
# terminal image setup we can use to run the init container. The image
# is what contains the script which copies the file into the persistent
# volume. Perhaps should use the JupyterHub image for the init container
# and add the script which performs the copy to this image.

volume_size = os.environ.get('VOLUME_SIZE')

if volume_size:
    c.KubeSpawner.pvc_name_template = '%s-user' % c.KubeSpawner.pod_name_template

    c.KubeSpawner.storage_pvc_ensure = True

    c.KubeSpawner.storage_capacity = volume_size

    c.KubeSpawner.storage_access_modes = ['ReadWriteOnce']

    c.KubeSpawner.volumes.extend([
        {
            'name': 'data',
            'persistentVolumeClaim': {
                'claimName': c.KubeSpawner.pvc_name_template
            }
        }
    ])

    c.KubeSpawner.volume_mounts.extend([
        {
            'name': 'data',
            'mountPath': '/opt/app-root',
            'subPath': 'workspace'
        }
    ])

    c.KubeSpawner.init_containers.extend([
        {
            'name': 'setup-volume',
            'image': '%s' % c.KubeSpawner.image_spec,
            'command': [
                '/opt/workshop/bin/setup-volume.sh',
                '/opt/app-root',
                '/mnt/workspace'
            ],
            "resources": {
                "limits": {
                    "memory": os.environ.get('WORKSHOP_MEMORY', '128Mi')
                },
                "requests": {
                    "memory": os.environ.get('WORKSHOP_MEMORY', '128Mi')
                }
            },
            'volumeMounts': [
                {
                    'name': 'data',
                    'mountPath': '/mnt'
                }
            ]
        }
    ])

# Read user logins file and set up rules to mapping to passwords.

user_logins_exact = {}

user_logins_match = []

if os.path.exists('/opt/app-root/configs/user_logins.csv'):
    with open('/opt/app-root/configs/user_logins.csv') as fp:
        for line in fp.readlines():
            line = line.strip()
            if line:
                user, password, project = line.split(',')
                if '*' in user or '?' in user or '[' in user:
                    user_logins_match.append((user, password, project))
                else:
                    user_logins_exact[user] = (password, project)

def lookup_user_details(user):
    if user in user_logins_exact:
        return user_logins_exact[user]

    for pattern, password, project in user_logins_match:
        if fnmatch(user, pattern):
            return (password, project)

# Make modifications to pod based on user and type of session.

@gen.coroutine
def modify_pod_hook(spawner, pod):
    details = lookup_user_details(spawner.user.name)

    if details:
        password, project = details

        password = password.format(username=spawner.user.name)
        project = project.format(username=spawner.user.name)

        if project:
            pod.spec.containers[0].env.append(
                    dict(name='PROJECT_NAMESPACE', value=project))

            # Create project name if it doesn't exist.

            pod.spec.containers[0].env.append(
                    dict(name='OPENSHIFT_PROJECT', value=project))

        else:
            # No project is created automatically. Assume that the project
            # which should be used is the same as the users name.

            pod.spec.containers[0].env.append(
                    dict(name='PROJECT_NAMESPACE', value=spawner.user.name))

        pod.spec.volumes.extend([
            {
                'name': 'kubeconfig',
                'emptyDir': {}
            }
        ])

        if not pod.spec.init_containers:
            pod.spec.init_containers = []

        pod.spec.init_containers.extend([
            {
                'name': 'setup-environ',
                'image': '%s' % pod.spec.containers[0].image,
                'command': [ '/opt/workshop/bin/setup-environ.sh' ],
                'env': [
                    {
                        'name': 'OPENSHIFT_USERNAME',
                        'value': spawner.user.name
                    },
                    {
                        'name': 'OPENSHIFT_PASSWORD',
                        'value': password
                    }
                ],
                "resources": {
                    "limits": {
                        "memory": os.environ.get('WORKSHOP_MEMORY', '128Mi')
                    },
                    "requests": {
                        "memory": os.environ.get('WORKSHOP_MEMORY', '128Mi')
                    }
                },
                'volumeMounts': [
                    {
                        'name': 'kubeconfig',
                        'mountPath': '/var/run/workshop'
                    }
                ]
            }
        ])

        pod.spec.containers[0].volume_mounts.extend([
            {
                'name': 'kubeconfig',
                'mountPath': '/var/run/workshop'
            }
        ])

        console_branding = os.environ.get('CONSOLE_BRANDING', 'openshift')

        pod.spec.containers.extend([
            {
                "name": "console",
                "image": "quay.io/openshift/origin-console:latest",
                "command": [ "bash", "-c", "set -x; export BRIDGE_K8S_AUTH_BEARER_TOKEN=`cat /var/run/workshop/token`; /opt/bridge/bin/bridge" ],
                "env": [
                    {
                        "name": "BRIDGE_BRANDING",
                        "value": "openshift"
                    },
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
                        "value": "/user/%s/console/" % spawner.user.name
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
                        "name": "BRIDGE_K8S_AUTH",
                        "value": "bearer-token"
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
                },
                'volumeMounts': [
                    {
                        'name': 'kubeconfig',
                        'mountPath': '/var/run/workshop'
                    }
                ]
            }
        ])

        pod.spec.containers[0].env.append(dict(name='CONSOLE_URL',
            value='http://localhost:10083'))

        pod.spec.automount_service_account_token = True

    else:
        # No project is created automatically. Assume that the project
        # which should be used is the same as the users name.

        pod.spec.containers[0].env.append(
                dict(name='PROJECT_NAMESPACE', value=spawner.user.name))

    return pod

c.KubeSpawner.modify_pod_hook = modify_pod_hook

# Setup culling of terminal instances if timeout parameter is supplied.

idle_timeout = os.environ.get('IDLE_TIMEOUT')

if idle_timeout and int(idle_timeout):
    c.JupyterHub.services.extend([
        {
            'name': 'cull-idle',
            'admin': True,
            'command': ['cull-idle-servers', '--timeout=%s' % idle_timeout],
        }
    ])

# Pass through for dashboard the URL where should be redirected in order
# to restart a session, with a new instance created with fresh image.

c.Spawner.environment['RESTART_URL'] = '/restart'

# Redirect handler for sending /restart back to home page for user.

from jupyterhub.handlers import BaseHandler

class RestartRedirectHandler(BaseHandler):

    @web.authenticated
    @gen.coroutine
    def get(self, *args):
        user = self.get_current_user()
        if user.running:
            status = yield user.spawner.poll_and_notify()
            if status is None:
                yield self.stop_single_user(user)
        self.redirect('/hub/spawn')

c.JupyterHub.extra_handlers.extend([
    (r'/restart$', RestartRedirectHandler),
])
