import os

import json
import requests

from kubernetes.client.rest import ApiException

from openshift.config import load_incluster_config
from openshift.client.api_client import ApiClient
from openshift.dynamic import DynamicClient, ResourceInstance

# Override styling elements for JupyterHub web pages.

c.JupyterHub.logo_file = '/opt/app-root/src/images/OpenShiftBanner.png'

# Override image details with that for the terminal. We need to use a
# fiddle at the moment and use the internal registry address for where
# the image policy plugin isn't configured for the cluster.

application_name = os.environ.get('APPLICATION_NAME')

service_account_name = '%s-hub' %  application_name
service_account_path = '/var/run/secrets/kubernetes.io/serviceaccount'

with open(os.path.join(service_account_path, 'namespace')) as fp:
    namespace = fp.read().strip()

terminal_image = os.environ.get('TERMINAL_IMAGE')

if not terminal_image:
    c.KubeSpawner.image_spec = (
            'docker-registry.default.svc:5000/%s/%s-app:latest' %
            (namespace, application_name))
else:
    c.KubeSpawner.image_spec = terminal_image

c.KubeSpawner.image_pull_policy = 'Always'

c.KubeSpawner.cmd = ['/usr/libexec/s2i/run']

c.KubeSpawner.pod_name_template = '%s-user-{username}' % (application_name)

c.Spawner.mem_limit = convert_size_to_bytes(os.environ['MEMORY_SIZE'])

# Work out the public server address for the OpenShift OAuth endpoint.
# Make sure request is done in a session so connection is closed and
# later calls against REST API don't attempt to reuse it. This is just
# to avoid potential for any problems with connection reuse.

server_url = 'https://openshift.default.svc.cluster.local'
oauth_metadata_url = '%s/.well-known/oauth-authorization-server' % server_url

with requests.Session() as session:
    response = session.get(oauth_metadata_url, verify=False)
    data = json.loads(response.content.decode('UTF-8'))
    address = data['issuer']

# Enable the OpenShift authenticator. The OPENSHIFT_URL environment
# variable must be set before importing the authenticator as it only
# reads it when module is first imported.

os.environ['OPENSHIFT_URL'] = address

from oauthenticator.openshift import OpenShiftOAuthenticator
c.JupyterHub.authenticator_class = OpenShiftOAuthenticator

# Setup authenticator configuration using details from environment.

client_id = 'system:serviceaccount:%s:%s' % (namespace, service_account_name)

c.OpenShiftOAuthenticator.client_id = client_id

with open(os.path.join(service_account_path, 'token')) as fp:
    client_secret = fp.read().strip()

c.OpenShiftOAuthenticator.client_secret = client_secret

# Work out hostname for the exposed route of the JupyterHub server. This
# is tricky as we need to use the REST API to query it.

load_incluster_config()

api_client = DynamicClient(ApiClient())

route_resource = api_client.resources.get(
     api_version='route.openshift.io/v1', kind='Route')

routes = route_resource.get(namespace=namespace)

def extract_hostname(routes, name):
    for route in routes.items:
        if route.metadata.name == name:
            return route.spec.host

public_hostname = extract_hostname(routes, application_name)

if not public_hostname:
    raise RuntimeError('Cannot calculate external host name for JupyterHub.')

c.OpenShiftOAuthenticator.oauth_callback_url = (
        'https://%s/hub/oauth_callback' % public_hostname)

c.Authenticator.auto_login = True

c.JupyterHub.admin_access = True

c.Authenticator.admin_users = set(os.environ.get('ADMIN_USERS', '').split())

c.Spawner.environment = dict(
        JUPYTERHUB_ROUTE='https://%s' % public_hostname)

if os.environ.get('OC_VERSION'):
    c.Spawner.environment['OC_VERSION'] = os.environ.get('OC_VERSION')
if os.environ.get('ODO_VERSION'):
    c.Spawner.environment['ODO_VERSION'] = os.environ.get('ODO_VERSION')
if os.environ.get('KUBECTL_VERSION'):
    c.Spawner.environment['KUBECTL_VERSION'] = os.environ.get('KUBECTL_VERSION')

# Override URL prefix for application and copy files to volume.

c.KubeSpawner.user_storage_pvc_ensure = True

c.KubeSpawner.pvc_name_template = '%s-user-{username}' % application_name

c.KubeSpawner.user_storage_capacity = os.environ['VOLUME_SIZE']

c.KubeSpawner.user_storage_access_modes = ['ReadWriteOnce']

c.KubeSpawner.volumes = [
    {
        'name': 'data',
        'persistentVolumeClaim': {
            'claimName': c.KubeSpawner.pvc_name_template
        }
    }
]

c.KubeSpawner.volume_mounts = [
    {
        'name': 'data',
        'mountPath': '/opt/app-root',
        'subPath': 'workspace'
    }
]

c.KubeSpawner.init_containers = [
    {
        'name': 'setup-volume',
        'image': '%s' % c.KubeSpawner.image_spec,
        'command': [
            '/opt/workshop/bin/setup-volume.sh',
            '/opt/app-root',
            '/mnt/workspace'
        ],
        'volumeMounts': [
            {
                'name': 'data',
                'mountPath': '/mnt'
            }
        ]
    }
]

# Setup culling of front end instance if timeout parameter is supplied.

idle_timeout = os.environ.get('IDLE_TIMEOUT')

if idle_timeout and int(idle_timeout):
    c.JupyterHub.services = [
        {
            'name': 'cull-idle',
            'admin': True,
            'command': ['cull-idle-servers', '--timeout=%s' % idle_timeout],
        }
    ]
