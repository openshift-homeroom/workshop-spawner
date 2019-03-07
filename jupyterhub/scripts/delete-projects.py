import threading
import time
import os

from collections import namedtuple

from kubernetes.client.rest import ApiException

from kubernetes.client.configuration import Configuration
from kubernetes.config.incluster_config import load_incluster_config
from kubernetes.client.api_client import ApiClient
from openshift.dynamic import DynamicClient

service_account_path = '/var/run/secrets/kubernetes.io/serviceaccount'

with open(os.path.join(service_account_path, 'namespace')) as fp:
    namespace = fp.read().strip()

with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace') as fp:
    namespace = fp.read().strip()

application_name = os.environ.get('APPLICATION_NAME')
service_account_name = '%s-%s-hub' %  (application_name, namespace)

load_incluster_config()

import urllib3
urllib3.disable_warnings()
instance = Configuration()
instance.verify_ssl = False
Configuration.set_default(instance)

api_client = DynamicClient(ApiClient())

pod_resource = api_client.resources.get(
     api_version='v1', kind='Pod')

service_account_resource = api_client.resources.get(
     api_version='v1', kind='ServiceAccount')

project_resource = api_client.resources.get(
     api_version='project.openshift.io/v1', kind='Project')

role_binding_resource = api_client.resources.get(
     api_version='rbac.authorization.k8s.io/v1', kind='RoleBinding')

project_cache = {}
user_cache = {}
orphan_cache = {}

Project = namedtuple('Project', ['name', 'user', 'pod'])

def get_projects():
    project_details = []

    full_account_name = 'system:serviceaccount:%s:%s' % (namespace,
            service_account_name)

    try:
        projects = project_resource.get(namespace=namespace)

        for project in projects.items:
            annotations = project.metadata.annotations
            requestor = annotations and annotations['openshift.io/requester']
            if requestor == full_account_name:
                description = annotations['openshift.io/description']
                if description:
                    fields = description.split('/')
                    if (len(fields) == 4 and fields[0] == namespace and
                            fields[1] == application_name):
                        project_details.append(Project(project.metadata.name,
                                fields[2], fields[3]))

    except Exception as e:
        print('ERROR: failed to list projects:', e)

    return project_details

def get_users():
    user_details = []

    hub_name = '%s-%s' % (application_name, namespace)

    try:
        users = service_account_resource.get(namespace=namespace)

        for user in users.items:
            labels = user.metadata.labels
            hub_label = labels and labels['hub']
            if hub_label == hub_name:
                user_details.append(user)

    except Exception as e:
        print('ERROR: failed to list users:', e)

    return user_details

def pod_exists(name):
    try:
        pod_resource.get(namespace=namespace, name=name)

        return True

    except ApiException as e:
        if e.status != 404:
            print('ERROR: failed to lookup pod %s:' % name, e)

    except Exception as e:
        print('ERROR: failed to lookup pod %s:' % name, e)

    return False

def delete_project(name):
    try:
        project_resource.delete(name=name)

        print('INFO: deleted project %s' % name)

    except ApiException as e:
        if e.status != 404:
            print('ERROR: failed to delete project %s:' % name, e)
        else:
            print('INFO: project %s already deleted' % name)

    except Exception as e:
        print('ERROR: failed to delete project %s:' % name, e)

def delete_user(name):
    try:
        service_account_resource.delete(namespace=namespace, name=name)
        print('INFO: deleted user %s' % name)

    except ApiException as e:
        if e.status != 404:
            print('ERROR: failed to delete user %s:' % name, e)
        else:
            print('INFO: user %s already deleted' % name)

    except Exception as e:
        print('ERROR: failed to delete user %s:' % name, e)

def purge():
    now = time.time()

    projects = get_projects()

    for project in projects:
        if not project in project_cache:
            project_cache[project] = now

        user_cache.setdefault(project.user, set()).add(project)

    for project in projects:
        if pod_exists(project.pod):
            project_cache[project] = now

    for project, last_seen in list(project_cache.items()):
        if now - last_seen > 150.0:
            user_cache[project.user].remove(project)

            if not user_cache[project.user]:
                delete_user(project.user)

                del user_cache[project.user]

            delete_project(project.name)

            del project_cache[project]

    users = get_users()

    for user in users:
        name = user.metadata.name
        if not name in user_cache:
            if not name in orphan_cache:
                orphan_cache[name] = now

    for name, last_seen in list(orphan_cache.items()):
        if name in user_cache:
            del orphan_cache[name]

        elif now - last_seen > 150.0:
            delete_user(name)

            del orphan_cache[name]

def loop():
    while True:
        try:
            purge()
        except Exception as e:
            print('ERROR: unexpected exception:', e)
            pass

        time.sleep(60.0)

thread = threading.Thread(target=loop)
thread.set_daemon = True
thread.start()

thread.join()
