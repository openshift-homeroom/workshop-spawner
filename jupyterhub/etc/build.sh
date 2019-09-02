#!/bin/bash

# Enable SCL packages for build.

source scl_source enable httpd24
source scl_source enable rh-python36
source scl_source enable $NODEJS_SCL

# Create the Python virtual environment.

virtualenv /opt/app-root

source /opt/app-root/bin/activate

pip install -U pip setuptools wheel

# Install the required application packages.

pip install -r requirements.txt

# Create data directory for database files.

mkdir /opt/app-root/data
