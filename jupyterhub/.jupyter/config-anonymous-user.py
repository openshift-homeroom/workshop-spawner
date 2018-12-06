# This file provides configuration specific to the 'anonymous-user'
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

import uuid
import string
import json

from tornado import gen

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

class AutoAuthenticateHandler(BaseHandler):

    def initialize(self, force_new_server, process_user):
        super().initialize()
        self.force_new_server = force_new_server
        self.process_user = process_user

    def generate_user(self):
        return ''.join(str(uuid.uuid1(0)).split('-')[:-1])

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
            ('/restart', AutoAuthenticateHandler, extra_settings)
        ]

    def login_url(self, base_url):
        return url_path_join(base_url, 'restart')

c.JupyterHub.authenticator_class = AutoAuthenticator

# Deploy embedded web console as a separate container within the same
# pod as the terminal instance. Currently use latest, but need to tie
# this to the specific OpenShift version once OpenShift 4.0 is released.

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
            }
        ],
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

project_request_resource = api_client.resources.get(
     api_version='project.openshift.io/v1', kind='ProjectRequest')

service_account_resource = api_client.resources.get(
     api_version='v1', kind='ServiceAccount')

secret_resource = api_client.resources.get(
     api_version='v1', kind='Secret')

role_binding_resource = api_client.resources.get(
     api_version='v1', kind='RoleBinding')

project_request_template = string.Template("""
{
    "kind": "ProjectRequest",
    "apiVersion": "project.openshift.io/v1",
    "metadata": {
        "name": "${name}",
        "labels": {
            "hub": "${hub}"
        }
    },
    "description": "${description}"
}
""")

role_binding_template = string.Template("""
{
    "kind": "RoleBinding",
    "apiVersion": "v1",
    "metadata": {
        "name": "${name}-${role}",
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
        "name": "${role}"
    }
}
""")

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

    while True:
        try:
            text = service_account_template.safe_substitute(
                    namespace=namespace, name=user_account_name, hub=hub)
            body = json.loads(text)

            service_account_resource.create(namespace=namespace, body=body)

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

    # Create a project for just this user. Poll to make sure it is
    # created before continue.

    try:
        description = '%s/%s/%s/%s' % (namespace, application_name,
                user_account_name, pod.metadata.name)

        text = project_request_template.safe_substitute(name=project_name,
                hub=hub, description=description)
        body = json.loads(text)

        project_request_resource.create(body=body)

    except ApiException as e:
        if e.status != 409:
            print('ERROR: Error creating project. %s' % e)
            raise

    except Exception as e:
        print('ERROR: Error creating project. %s' % e)
        raise

    for _ in range(20):
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

        print('ERROR: Could not verify project. %s' % project_name)

    # Create role binding in the project so the hub service account
    # can delete project when done. Will fail if the project hasn't
    # actually been created yet.

    try:
        text = role_binding_template.safe_substitute(
                namespace=namespace, name=hub_account_name,
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

    # Create role binding in the project so the users service account
    # can create resources in it. Need to give it 'admin' role and not
    # just 'edit' so that can grant roles to service accounts in the
    # project. This means it could though delete the project itself, and
    # if do that can't create a new one as has no rights to do that.

    try:
        text = role_binding_template.safe_substitute(
                namespace=namespace, name=user_account_name,
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

    # Add environment variable for the users namespace for use in any
    # workshop content.

    pod.spec.containers[0].env.append(
            dict(name='USER_NAMESPACE', value=project_name))

    return pod

c.KubeSpawner.modify_pod_hook = modify_pod_hook

# Setup culling of terminal instances when idle or session expires, as
# well as setup service to clean up service accounts and projects related
# to old sessions.

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
