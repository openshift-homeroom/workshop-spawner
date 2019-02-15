# This file provides configuration specific to the 'hosted-workshop'
# deployment mode. In this mode authentication for JupyterHub is done
# against the OpenShift cluster using OAuth.

# Work out the public server address for the OpenShift OAuth endpoint.
# Make sure the request is done in a session so the connection is closed
# and later calls against the REST API don't attempt to reuse it. This
# is just to avoid potential for any problems with connection reuse.

import json
import requests

server_host = os.environ['KUBERNETES_PORT_443_TCP_ADDR']
server_url = 'https://%s' % server_host

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

# No project is created automatically. Assume that the project which
# should be used is the same as the users name.

import operator

c.Spawner.environment['PROJECT_NAMESPACE'] = operator.attrgetter('user.name')

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

    c.KubeSpawner.init_containers.extend([
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
    ])

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

from tornado import web, gen

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
