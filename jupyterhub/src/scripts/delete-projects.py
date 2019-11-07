import threading
import time
import os

from collections import namedtuple

from kubernetes.client.rest import ApiException

from kubernetes.client.configuration import Configuration
from kubernetes.config.incluster_config import load_incluster_config
from kubernetes.client.api_client import ApiClient
from openshift.dynamic import DynamicClient, Resource

service_account_path = '/var/run/secrets/kubernetes.io/serviceaccount'

with open(os.path.join(service_account_path, 'namespace')) as fp:
    namespace = fp.read().strip()

with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace') as fp:
    namespace = fp.read().strip()

workshop_name = os.environ.get('WORKSHOP_NAME')

application_name = os.environ.get('APPLICATION_NAME')

if not application_name:
    workshop_name = application_name

if not workshop_name:
    workshop_name = 'homeroom'

service_account_name = '%s-spawner' %  application_name

full_service_account_name = 'system:serviceaccount:%s:%s' % (namespace,
        service_account_name)

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

namespace_resource = api_client.resources.get(
     api_version='v1', kind='Namespace')

role_binding_resource = api_client.resources.get(
     api_version='rbac.authorization.k8s.io/v1', kind='RoleBinding')

project_cache = {}
account_cache = {}
orphan_cache = {}

Namespace = namedtuple('Namespace', ['name', 'account', 'pod'])

def get_projects():
    project_details = []

    try:
        projects = namespace_resource.get(namespace=namespace)

        for project in projects.items:
            annotations = project.metadata.annotations
            if annotations:
                if (annotations['spawner/requestor'] == full_service_account_name and 
                        annotations['spawner/namespace'] == namespace and
                        annotations['spawner/deployment'] == application_name):
                    project_details.append(Namespace(project.metadata.name,
                            annotations['spawner/account'],
                            annotations['spawner/session']))

    except Exception as e:
        print('ERROR: failed to list projects:', e)

    return project_details

def get_accounts():
    account_details = []

    try:
        accounts = service_account_resource.get(namespace=namespace)

        for account in accounts.items:
            labels = account.metadata.labels
            application_label = labels and labels['app']
            if application_label == application_name and labels['user']:
                account_details.append(account)

    except Exception as e:
        print('ERROR: failed to list accounts:', e)

    return account_details

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

def namespaced_resources():
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
                            yield resource
                except Exception:
                    pass

def purge_project(name):
    for resource_type in namespaced_resources():
        try:
            objects = resource_type.get(namespace=name)
            for obj in objects.items:
                if obj.metadata.deletionTimestamp and obj.metadata.finalizers:
                    # Since the project is stuck in terminating, we
                    # remove any finalizers which might be blocking
                    # it. Finalizers can be left around with nothing
                    # to remove them because there is no gaurantee
                    # what order resources will be deleted when a
                    # project is deleted. Thus an application, for
                    # example an operator which would remove the
                    # finalizer when a CRD is deleted, might get
                    # deleted before the objects with the finalizer,
                    # and so the objects can't then be deleted.

                    body = {
                        'kind': obj.kind,
                        'apiVersion': obj.apiVersion,
                        'metadata': {
                            'name': obj.metadata.name,
                            'finalizers': None
                        }
                    }

                    print('WARNING: deleting finalizers on resource: %s' % body)

                    try:
                        resource_type.patch(namespace=name, body=body,
                                content_type='application/merge-patch+json')

                    except ApiException as e:
                        print('ERROR: failed to delete finalizers: %s' % body, e)

                    except Exception as e:
                        print('ERROR: failed to delete finalizers: %s' % body, e)

        except ApiException as e:
            if e.status not in (403, 404, 405):
                print('ERROR: failed to query resources %s' % resource_type, e)

        except Exception as e:
            print('ERROR: failed to query resources %s' % resource_type, e)

    pass

def delete_project(name):
    try:
        namespace_resource.delete(name=name)

        print('INFO: deleted project %s' % name)

    except ApiException as e:
        if e.status == 409:
            print('WARNING: project %s is still terminating' % name)
            purge_project(name)
        elif e.status != 404:
            print('ERROR: failed to delete project %s:' % name, e)
        else:
            print('INFO: project %s already deleted' % name)

    except Exception as e:
        print('ERROR: failed to delete project %s:' % name, e)

def delete_account(name):
    try:
        service_account_resource.delete(namespace=namespace, name=name)
        print('INFO: deleted account %s' % name)

    except ApiException as e:
        if e.status != 404:
            print('ERROR: failed to delete account %s:' % name, e)
        else:
            print('INFO: account %s already deleted' % name)

    except Exception as e:
        print('ERROR: failed to delete account %s:' % name, e)

def purge():
    now = time.time()

    projects = get_projects()

    if projects:
        print('INFO: checking for projects to be deleted: %s' % projects)

    for project in projects:
        if not project in project_cache:
            project_cache[project] = now

        account_cache.setdefault(project.account, set()).add(project)

    for project in projects:
        if pod_exists(project.pod):
            project_cache[project] = now

    for project, last_seen in list(project_cache.items()):
        if now - last_seen > 90.0:
            account_cache[project.account].remove(project)

            if not account_cache[project.account]:
                delete_account(project.account)

                del account_cache[project.account]

            delete_project(project.name)

            del project_cache[project]

    accounts = get_accounts()

    for account in accounts:
        name = account.metadata.name
        if not name in account_cache:
            if not name in orphan_cache:
                orphan_cache[name] = now

    for name, last_seen in list(orphan_cache.items()):
        if name in account_cache:
            del orphan_cache[name]

        elif now - last_seen > 90.0:
            delete_account(name)

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
