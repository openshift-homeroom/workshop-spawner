# This file provides configuration specific to the 'hosted-workshop'
# deployment mode. In this mode authentication for JupyterHub is done
# against the OpenShift cluster using OAuth.

# Work out the public server address for the OpenShift OAuth endpoint.
# Make sure the request is done in a session so the connection is closed
# and later calls against the REST API don't attempt to reuse it. This
# is just to avoid potential for any problems with connection reuse.

from fnmatch import fnmatch

from tornado import web, gen

oauth_metadata_url = '%s/.well-known/oauth-authorization-server' % kubernetes_server_url

with requests.Session() as session:
    response = session.get(oauth_metadata_url, verify=False)
    data = json.loads(response.content.decode('UTF-8'))
    oauth_issuer_address = data['issuer']

# Enable the OpenShift authenticator. Environments variables have
# already been set from the hosted-workshop.sh script file.

c.JupyterHub.authenticator_class = "openshift"

OpenShiftOAuthenticator.scope = ['user:full']

client_id = '%s-%s-console' % (application_name, namespace)
client_secret = os.environ['OAUTH_CLIENT_SECRET']

c.OpenShiftOAuthenticator.client_id = client_id
c.OpenShiftOAuthenticator.client_secret = client_secret
c.Authenticator.enable_auth_state = True

c.CryptKeeper.keys = [ client_secret.encode('utf-8') ]

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

# Deploy embedded web console as a separate container within the same
# pod as the terminal instance. Currently use latest, but need to tie
# this to the specific OpenShift version once OpenShift 4.0 is released.

console_branding = os.environ.get('CONSOLE_BRANDING', 'openshift')
console_image = os.environ.get('CONSOLE_IMAGE', 'quay.io/openshift/origin-console:4.1')

c.KubeSpawner.extra_containers.extend([
    {
        "name": "console",
        "image": console_image,
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
        }
    }
])

c.Spawner.environment['CONSOLE_URL'] = 'http://localhost:10083'

# Pass through environment variables with remote workshop details.

c.Spawner.environment['DOWNLOAD_URL'] = os.environ.get('DOWNLOAD_URL', '')
c.Spawner.environment['WORKSHOP_FILE'] = os.environ.get('WORKSHOP_FILE', '')

# Make modifications to pod based on user and type of session.

@gen.coroutine
def modify_pod_hook(spawner, pod):
    # Set the session access token from the OpenShift login in
    # both the terminal and console containers. We still mount
    # the service account token still as well because the console
    # needs the SSL certificate contained in it when accessing
    # the cluster REST API.

    auth_state = yield spawner.user.get_auth_state()

    pod.spec.containers[0].env.append(
            dict(name='OPENSHIFT_TOKEN', value=auth_state['access_token']))

    pod.spec.containers[-1].env.append(
            dict(name='BRIDGE_K8S_AUTH_BEARER_TOKEN',
            value=auth_state['access_token']))

    pod.spec.service_account_name = '%s-%s-user' % (application_name, namespace)
    pod.spec.automount_service_account_token = True

    # See if a template for the project name has been specified.
    # Try expanding the name, substituting the username. If the
    # result is different then we use it, not if it is the same
    # which would suggest it isn't unique.

    project = os.environ.get('OPENSHIFT_PROJECT')

    if project:
        name = project.format(username=spawner.user.name)
        if name != project:
            pod.spec.containers[0].env.append(
                    dict(name='PROJECT_NAMESPACE', value=name))

            # Ensure project is created if it doesn't exist.

            pod.spec.containers[0].env.append(
                    dict(name='OPENSHIFT_PROJECT', value=name))

    return pod

c.KubeSpawner.modify_pod_hook = modify_pod_hook

# Setup culling of terminal instances if timeout parameter is supplied.

idle_timeout = os.environ.get('IDLE_TIMEOUT')

if idle_timeout and int(idle_timeout):
    cull_idle_servers_cmd = ['/opt/app-root/src/scripts/cull-idle-servers.sh']

    cull_idle_servers_cmd.append('--timeout=%s' % idle_timeout)

    c.JupyterHub.services.extend([
        {
            'name': 'cull-idle',
            'admin': True,
            'command': cull_idle_servers_cmd,
            'environment': dict(
                ENV="/opt/app-root/etc/profile",
                BASH_ENV="/opt/app-root/etc/profile",
                PROMPT_COMMAND=". /opt/app-root/etc/profile"
            ),
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
        user = yield self.get_current_user()
        if user.running:
            status = yield user.spawner.poll_and_notify()
            if status is None:
                yield self.stop_single_user(user)
        self.redirect('/hub/spawn')

c.JupyterHub.extra_handlers.extend([
    (r'/restart$', RestartRedirectHandler),
])
