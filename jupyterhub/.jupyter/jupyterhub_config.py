import os

# This file provides common configuration for the different ways that
# the deployment can run. The configuration types are 'hosted-workshop'
# and 'learning-portal'. Configuration specific to the different modes
# will be read from separate files at the end of this configuration
# file.

# The application name and configuration type are passed in through the
# template. The application name should be the value used for the
# deployment, and more specifically, must match the name of the route.
# The configuration type will vary based on the template, as the setup
# required for each will be different.
#
# The name 'workshop-terminals' was old identifier. Keep for now, mapping
# to 'hosted-workshop', but need to remove it at some point.

application_name = os.environ.get('APPLICATION_NAME')

configuration_type = os.environ.get('CONFIGURATION_TYPE', 'hosted-workshop')

if configuration_type == 'workshop-terminals':
    configuration_type = 'hosted-workshop'

# Override styling elements for the JupyterHub web pages.

c.JupyterHub.logo_file = '/opt/app-root/src/images/OpenShiftBanner.png'

# Work out the service account name and name of the namespace that the
# deployment is in.

service_account_name = '%s-hub' %  application_name

service_account_path = '/var/run/secrets/kubernetes.io/serviceaccount'

with open(os.path.join(service_account_path, 'namespace')) as fp:
    namespace = fp.read().strip()

# Override the default name template for the pod so we include both the
# application name and namespace. Don't change this as 'event' module
# relies on it being this name to make it easier to match up a pod to
# the temporary project created for that session.

c.KubeSpawner.pod_name_template = '%s-%s-{username}' % (
        application_name, namespace)

# Use a higher port number for the terminals spawned by JupyterHub so
# that secondary applications run from within the terminal can use port
# 8080 for testing, or so that port can be exposed by a separate route.

c.KubeSpawner.port = 10080

# Initialise the set of environment variables to be empty so we know it
# is a dict. This is so we can incrementally add values as we go along.

c.Spawner.environment = dict()

# Initialise the set of services to be empty so we know it is a list.
# This is so we can incrementally add values as we go along.

c.JupyterHub.services = []

# Initialise the set of init containers to be empty so we know it is
# a list. This is so we can incrementally add values as we go along.

c.KubeSpawner.init_containers = []

# Initialise the set of extra containers to be empty so we know it is
# a list. This is so we can incrementally add values as we go along.

c.KubeSpawner.extra_containers = []

# Initialise the set of extra handlers to be empty so we know it is
# a list. This is so we can incrementally add values as we go along.

c.JupyterHub.extra_handlers = []

# Override the image details with that for the terminal or dashboard
# image being used. The default is to assume that a image stream with
# '-app' extension for the application name is used. The call to the
# function resolve_image_name() is to try and resolve to image registry
# when using image stream. This is to workaround issue that many
# clusters do not have image policy controller configured correctly.
#
# Note that we set the policy that images will always be pulled to the
# node each time when the image name is not explicitly provided. This is
# so that during development, changes to the terminal image will always
# be picked up. Someone developing a new image need only update the
# 'latest' tag on the '-app' image using 'oc tag'. 

terminal_image = os.environ.get('TERMINAL_IMAGE')

if not terminal_image:
    c.KubeSpawner.image_pull_policy = 'Always'
    terminal_image = '%s-app:latest' % application_name

c.KubeSpawner.image_spec = resolve_image_name(terminal_image)

# Override the command run in the terminal image as we aren't deploying
# Jupyter notebooks but our terminal image.

c.KubeSpawner.cmd = ['/usr/libexec/s2i/run']

# Set the default amount of memory provided to a pod. This might be
# overridden on a case by case for images if a profile list is supplied
# so users have a choice of images when deploying workshop content.

c.Spawner.mem_limit = convert_size_to_bytes(
        os.environ.get('WORKSHOP_MEMORY', '512Mi'))

# Work out hostname for the exposed route of the JupyterHub server. This
# is tricky as we need to use the REST API to query it. We assume that
# a secure route is always used. This is used when needing to do OAuth.

from openshift.config import load_incluster_config
from openshift.client.api_client import ApiClient
from openshift.dynamic import DynamicClient

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

c.Spawner.environment['JUPYTERHUB_ROUTE'] = 'https://%s' % public_hostname

# Work out the subdomain under which applications hosted in the cluster
# are hosted. Calculate this from the route for the JupyterHub route if
# not supplied explicitly.

cluster_subdomain = os.environ.get('CLUSTER_SUBDOMAIN')

if not cluster_subdomain:
    cluster_subdomain = '.'.join(public_hostname.split('.')[1:])

c.Spawner.environment['CLUSTER_SUBDOMAIN'] = cluster_subdomain

# The terminal image will normally work out what versions of OpenShift
# and Kubernetes command line tools should be used, based on the version
# of OpenShift which is being used. Allow these to be overridden if
# necessary.

if os.environ.get('OC_VERSION'):
    c.Spawner.environment['OC_VERSION'] = os.environ.get('OC_VERSION')
if os.environ.get('ODO_VERSION'):
    c.Spawner.environment['ODO_VERSION'] = os.environ.get('ODO_VERSION')
if os.environ.get('KUBECTL_VERSION'):
    c.Spawner.environment['KUBECTL_VERSION'] = os.environ.get('KUBECTL_VERSION')

# Load configuration corresponding to the deployment mode.

config_root = '/opt/app-root/src/.jupyter'
config_file = '%s/config-%s.py' % (config_root, configuration_type)

if os.path.exists(config_file):
    with open(config_file) as fp:
        exec(compile(fp.read(), config_file, 'exec'), globals())
