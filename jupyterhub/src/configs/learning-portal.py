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

import time
import functools
import random
import weakref

from tornado import gen, web

from jupyterhub.auth import Authenticator
from jupyterhub.handlers import BaseHandler
from jupyterhub.utils import url_path_join

from kubernetes.client.rest import ApiException

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
        raw_user = yield self.get_current_user()

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

named_users = weakref.WeakValueDictionary()

user_count = 0

def generate_sequential_userid():
    global user_count
    user_count += 1
    return 'user%d' % user_count

class NamedUserAuthenticator(Authenticator):
    password = os.environ.get('SPAWNER_PASSWORD')

    def generate_user(self, username):
        user = named_users.get(username)

        if user:
            return user.name

        while True:
            name = generate_sequential_userid()
            user = get_user_details(name)
            if not user.active:
                user.active = True
                named_users[username] = user
                return name

    @gen.coroutine
    def authenticate(self, handler, data):
        if data['username'] and self.password:
            if data['password'] == self.password:
                return self.generate_user(data['username'])

if NamedUserAuthenticator.password:
    c.JupyterHub.authenticator_class = NamedUserAuthenticator

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

# Pass through for dashboard the URL where should be redirected in order
# to restart a session, with a new instance created with fresh image.

c.Spawner.environment['RESTART_URL'] = '/restart'

# Intercept creation of pod and used it to trigger our customisations.

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

    owner_uid = yield create_service_account(spawner, pod)

    # If there are any exposed ports defined for the session, create
    # a service object mapping to the pod for the ports, and create
    # routes for each port.

    exposed_ports = os.environ.get('EXPOSED_PORTS', '')

    if exposed_ports:
        exposed_ports = exposed_ports.split(',')

        try:
            text = service_template.safe_substitute(
                    configuration=configuration_type, name=user_account_name,
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
                text = route_template.safe_substitute(
                        configuration=configuration_type,
                        name=user_account_name, hub=hub, port='%s' % port,
                        username=short_name, uid=owner_uid, host=host)
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

        text = namespace_template.safe_substitute(
                configuration=configuration_type, name=project_name,
                hub=hub, requestor=service_account_name, namespace=namespace,
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

    # Now set up the project permissions and resource budget.

    resource_budget = os.environ.get('RESOURCE_BUDGET', 'default')

    project_uid = yield setup_project_namespace(spawner, pod, project_name,
            'admin', resource_budget)

    # Before can continue, need to poll looking to see if the secret for
    # the api token has been added to the service account. If don't do
    # this then pod creation will fail immediately. To do this, must get
    # the secrets from the service account and make sure they in turn
    # exist.

    yield wait_on_service_account(user_account_name)

    # Create any extra resources in the project required for a workshop.

    yield create_extra_resources(spawner, pod, project_name, project_uid,
            user_account_name, short_name)

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
    cull_idle_servers_cmd = ['/opt/app-root/src/scripts/cull-idle-servers.sh']

    cull_idle_servers_cmd.append('--cull-every=60')
    cull_idle_servers_cmd.append('--timeout=%s' % idle_timeout)
    cull_idle_servers_cmd.append('--cull-users')

    if max_session_age:
        cull_idle_servers_cmd.append('--max-age=%s' % max_session_age)

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

    delete_projects_cmd = ['/opt/app-root/src/scripts/delete-projects.sh']

    c.JupyterHub.services.extend([
        {
            'name': 'delete-projects',
            'command': delete_projects_cmd,
            'environment': dict(
                ENV="/opt/app-root/etc/profile",
                BASH_ENV="/opt/app-root/etc/profile",
                PROMPT_COMMAND=". /opt/app-root/etc/profile",
                APPLICATION_NAME=application_name,
                KUBERNETES_SERVICE_HOST=kubernetes_service_host,
                KUBERNETES_SERVICE_PORT=kubernetes_service_port
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
        user = yield self.get_current_user()

        if user.running:
            status = yield user.spawner.poll_and_notify()
            if status is None:
                yield self.stop_single_user(user)
        self.clear_login_cookie()
        self.redirect(homeroom_link or '/hub/spawn')

c.JupyterHub.extra_handlers.extend([
    (r'/restart$', RestartRedirectHandler),
])
