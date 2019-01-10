# This file provides configuration specific to the 'terminal-server'
# deployment mode. In this mode authentication for JupyterHub is done
# against a KeyCloak authentication server.

# Configure KeyCloak as the authentication provider for users.

keycloak_name = '%s-keycloak' % application_name
keycloak_hostname = extract_hostname(routes, keycloak_name)
keycloak_realm = 'jupyterhub'

os.environ['OAUTH2_TOKEN_URL'] = 'https://%s/auth/realms/%s/protocol/openid-connect/token' % (keycloak_hostname, keycloak_realm)
os.environ['OAUTH2_AUTHORIZE_URL'] = 'https://%s/auth/realms/%s/protocol/openid-connect/auth' % (keycloak_hostname, keycloak_realm)
os.environ['OAUTH2_USERDATA_URL'] = 'https://%s/auth/realms/%s/protocol/openid-connect/userinfo' % (keycloak_hostname, keycloak_realm)

os.environ['OAUTH2_TLS_VERIFY'] = '0'
os.environ['OAUTH_TLS_VERIFY'] = '0'

os.environ['OAUTH2_USERNAME_KEY'] = 'preferred_username'

from oauthenticator.generic import GenericOAuthenticator
c.JupyterHub.authenticator_class = GenericOAuthenticator

c.OAuthenticator.login_service = "KeyCloak"

c.OAuthenticator.oauth_callback_url = 'https://%s/hub/oauth_callback' % public_hostname

c.OAuthenticator.client_id = 'jupyterhub'
c.OAuthenticator.client_secret = os.environ.get('OAUTH_CLIENT_SECRET')

c.OAuthenticator.tls_verify = False

# Enable admin access to designated users of the OpenShift cluster.

c.JupyterHub.admin_access = True

c.Authenticator.admin_users = set(os.environ.get('ADMIN_USERS', '').split())

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

c.KubeSpawner.pvc_name_template = c.KubeSpawner.pod_name_template

c.KubeSpawner.storage_pvc_ensure = True

c.KubeSpawner.storage_capacity = os.environ.get('VOLUME_SIZE', '1Gi')

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

# Redirect handler for sending /restart back to home page for user.

from tornado import web

from jupyterhub.handlers import BaseHandler

class RestartRedirectHandler(BaseHandler):

    @web.authenticated
    def get(self, *args):
        self.redirect('/')

c.JupyterHub.extra_handlers.extend([
    (r'/restart$', RestartRedirectHandler),
])
