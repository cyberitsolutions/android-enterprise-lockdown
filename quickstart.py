#!/usr/bin/python3

__DOC__ = """ talk to EMM server *at all* from ordinary Python

See also https://github.com/google/android-management-api-samples/blob/master/notebooks/quickstart.ipynb

"""

# Copyright 2018 Google LLC.
# © Trent W. Buck

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

# https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

######################################################################
## Setup
######################################################################
# The base resource of your Android Management solution is a Google Cloud Platform project.
# All other resources (`Enterprises`, `Devices`, `Policies`, etc) belong to the project, and
# the project controls access to these resources.
#
# A solution is typically associated with a single project, but
# you can create multiple projects if you want to restrict access to resources.
#
# You can create a project in the Google Cloud Console:
#
#   1. Go to the Cloud Console: https://console.cloud.google.com/cloud-resource-manager
#   2. Click `CREATE PROJECT`.
#   3. Enter your project details, and then click `CREATE`.
#   4. Read and remember the project ID; run ./quickstart.py --project-id=X.


import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--project-id', default='frobozz')

# To create and access resources,
# you must authenticate with an account that has edit rights over your project.
# To start the authentication flow, run the cell below.
#
# When you build a server-based solution, you should create a
# service account so you don't need to authorize the access every time.
#
#     https://developers.google.com/android/management/service-account

from apiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# FIXME: CHANGE THESE MAGIC NUMBERS;
#        DO NOT HARD-CODE THEM IN A PUBLIC REPO!
# This is a public OAuth config, you can use it to run this guide, but
# please use different credentials when building your own solution.
CLIENT_CONFIG = {
    'installed': {
        'client_id':'882252295571-uvkkfelq073vq73bbq9cmr0rn8bt80ee.apps.googleusercontent.com',
        'client_secret': 'S2QcoBe0jxNLUoqnpeksCLxI',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://accounts.google.com/o/oauth2/token'
    }
}
SCOPES = ['https://www.googleapis.com/auth/androidmanagement']

# Run the OAuth flow.
flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
credentials = flow.run_console()

# Create the API client.
androidmanagement = build('androidmanagement', 'v1', credentials=credentials)

print('\nAuthentication succeeded.')

######################################################################
## Create an enterprise
######################################################################
# An `Enterprise` resource binds an organization to your Android Management solution.
# `Devices` and `Policies` both belong to an enterprise.
# Typically, a single enterprise resource is associated with a single organization.
# However, you can create multiple enterprises for the same organization based on their needs.
# For example, an organization may want separate enterprises for its different departments or regions.
#
# To create an enterprise you need a Gmail account.
# It MUST NOT already be associated with an enterprise.
#
# To start the enterprise creation flow, run the cell below.
#
# If you've already created an enterprise for this project,
# you can skip this step and enter your enterprise name in the next cell.

CALLBACK_URL = 'https://storage.googleapis.com/android-management-quick-start/enterprise_signup_callback.html'

# Generate a signup URL where the enterprise admin can signup with a Gmail
# account.
signup_url = androidmanagement.signupUrls().create(
    projectId=cloud_project_id,
    callbackUrl=CALLBACK_URL
).execute()

print('Please visit this URL to create an enterprise:', signup_url['url'])

enterprise_token = input('Enter the code: ')

# Complete the creation of the enterprise and retrieve the enterprise name.
enterprise = androidmanagement.enterprises().create(
    projectId=cloud_project_id,
    signupUrlName=signup_url['name'],
    enterpriseToken=enterprise_token,
    body={}
).execute()

enterprise_name = enterprise['name']

print('\nYour enterprise name is', enterprise_name)

# Take note of the enterprise name so you can reuse it after you close this notebook.
# If you already have an enterprise, you can enter the enterprise name in the cell below and run the cell.

# Paste your enterprise name here.
enterprise_name = ''

######################################################################
## Create a policy
######################################################################
#
# A `Policy` is a group of settings that determine the behavior of a managed device and apps installed thereon.
# Each Policy resource represents a unique group of device and app settings and can be applied to one or more devices.
# Once a device is linked to a policy, any updates to the policy are automatically applied to the device.
#
# To create a basic policy, run the cell below.
# You'll see how to create more advanced policies later in this guide.


import json

policy_name = enterprise_name + '/policies/policy1'

policy_json = '''
{
  "applications": [
    {
      "packageName": "com.google.samples.apps.iosched",
      "installType": "FORCE_INSTALLED"
    }
  ],
  "debuggingFeaturesAllowed": true
}
'''

androidmanagement.enterprises().policies().patch(
    name=policy_name,
    body=json.loads(policy_json)
).execute()


######################################################################
## Provision a device
######################################################################
# Provisioning refers to the process of enrolling a device with an enterprise,
# applying the appropriate policies to the device, and
# guiding the user to complete the set up of their device in accordance with those policies.
# Before attempting to provision a device,
# ensure that the device is running Android 6.0 or above.
#
# You need an enrollment token for each device that you want to provision (you can use the same token for multiple devices);
# when creating a token you can specify a policy that will be applied to the device.

enrollment_token = androidmanagement.enterprises().enrollmentTokens().create(
    parent=enterprise_name,
    body={"policyName": policy_name}
).execute()


# Embed your enrollment token in either an enrollment link or a QR code, and then follow the provisioning instructions below.


from urllib.parse import urlencode

image = {
    'cht': 'qr',
    'chs': '500x500',
    'chl': enrollment_token['qrCode']
}

qrcode_url = 'https://chart.googleapis.com/chart?' + urlencode(image)

print('Please visit this URL to scan the QR code:', qrcode_url)




enrollment_link = 'https://enterprise.google.com/android/enroll?et=' + enrollment_token['value']

print('Please open this link on your device:', enrollment_link)



# The method for provisioning a device varies depending on the management mode you want to use.
#
# Fully managed mode
# ------------------------------------------------------------
# In fully managed mode the entire device is managed and the device needs to be factory reset before setup.
# To set up a device in fully managed mode you need to use a QR code.
#
# For devices running Android 7.0 or above:
#
# 1.  Turn on a new or factory-reset device.
# 2.  Tap the same spot on the welcome screen six times to enter QR code mode.
# 3.  Connect to a WiFi network.
# 4.  Scan the QR code.
#
# For devices running Android 6.0:
#
# 1.  Turn on a new or factory-reset device.
# 2.  Follow the setup wizard and enter your Wi-Fi details.
# 3.  When prompted to sign in, enter **afw#setup**.
# 4.  Tap Next, and then accept the installation of Android Device Policy.
# 5.  Scan the QR code.
#
# Work profile mode
# ------------------------------------------------------------
# In work profile mode corporate apps and data are kept secure in a self-contained work profile
# while the user keeps control of the rest of the device.
# To set up a work profile you can either use a QR code or an enrollment link.
#
# Using the enrollment link:
#
# 1.  Make the link accessible on the device (send it via email or put it on a website).
# 2.  Open the link.
#
# Or using the QR code:
#
# 1.  Go to Settings > Google.
# 2.  Tap "Set up your work profile".
# 3.  Scan the QR code.

######################################################################
## What's next?
######################################################################
# By now you should have a managed device configured with a basic policy, but
# there's much more you can do with the Android Management API.
#
# First, we recommend exploring the range of available policies to build the right policy for your needs:
#    https://developers.google.com/android/management/create-policy
#
# Next, explore other features of the Android Management API:
#
#  • Learn how to discover apps:
#    https://developers.google.com/android/management/apps
#
#  • Set up Pub/Sub notifications
#    https://developers.google.com/android/management/notifications
#
# Or start developing a server-based solution:
#
#  • Download the Android Management API client library for
#
#      :Java:   https://developers.google.com/api-client-library/java/apis/androidmanagement/v1
#      :.NET:   https://developers.google.com/api-client-library/dotnet/apis/androidmanagement/v1
#      :Python: https://developers.google.com/api-client-library/python/apis/androidmanagement/v1 or
#      :Ruby:   https://developers.google.com/api-client-library/ruby/apis/androidmanagement/v1
#
#  • Create a service account
#    https://developers.google.com/android/management/service-account
