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
import base64
import json
import logging
import os
import pathlib
import subprocess
import urllib.parse

import apiclient.discovery
import google.oauth2.service_account
import google_auth_oauthlib.flow
import googleapiclient
import jsmin                 # purely so policy file can have comments
import pypass
import requests                 # purely for get().json() shorthand

parser = argparse.ArgumentParser(description=__DOC__)
parser.add_argument(
    'json_config_path',
    nargs='?',
    default=pathlib.Path('frobozz-policies.jsonc'),
    type=pathlib.Path,
    # example='android-management-api-client@frobozz.iam.gserviceaccount.com',
    help="""
    A file containing a JSON object with at least {"policies": {"my-cool-policy": ...}}.
    If it contains "gcloud_project_id" you won't be prompted for one.
    If it contains "enterprise_name" you won't be prompted to create one.
    Note that "enterprise_name" is a token provided by Google, NOT one you make up.
    If it contains "gcloud_service_account" it'll be looked up in ~/.password-store.
    Otherwise, you will have to bounce through a browser every time.
    """)
parser.add_argument(
    '--work-profile-mode', action='store_true',
    help="""
    Emit enrollment URL instead of enrollment QR code.
    QR code is easier for "fully managed mode" (device only has restricted work account).
    URL is easier for "work profile mode" (device has an unrestricted non-work account).
    """)
parser.add_argument(
    '--enrollment-policy-name',
    help="""
    At the end of this garbage script, it generates an enrollment QR code for SOME policy.
    Which one is semi-random.  To force a specific one, use this.
    e.g. --enrollment-policy-name=policy1
    """)
parser.add_argument('--hurry-the-fuck-up', action='store_true')
parser.add_argument('--debug', dest='logging_level', action='store_const', const=logging.DEBUG, default=logging.NOTSET)
parser.add_argument('--verbose', dest='logging_level', action='store_const', const=logging.INFO, default=logging.NOTSET)
args = parser.parse_args()
logging.getLogger().setLevel(args.logging_level)

with args.json_config_path.open() as f:
    json_config_object = json.loads(jsmin.jsmin(f.read()))

# Sanity check
if args.enrollment_policy_name:
    if args.enrollment_policy_name not in json_config_object['policies']:
        raise RuntimeError('Bogus enrollment policy name',
                           args.enrollment_policy_name,
                           json_config_object['policies'].keys())

if 'service_account' in json_config_object:
    # first-time setup has already been done, so get an oauth token from the private key.
    service_account_object = json.loads(
        pypass.PasswordStore().get_decrypted_password(
            json_config_object['service_account']).strip())
    # Basic sanity checks
    if service_account_object['type'] != 'service_account':
        raise RuntimeError('wrong json')
    if 'private_key' not in service_account_object:
        raise RuntimeError('wrong json')
    gcloud_project_id = service_account_object['project_id']
    logging.debug('Project ID is: %s', gcloud_project_id)
    androidmanagement = apiclient.discovery.build(
        serviceName='androidmanagement',
        version='v1',
        cache_discovery=False,  # disable some stupid warning
        credentials=google.oauth2.service_account.Credentials.from_service_account_info(
            info=service_account_object,
            scopes=['https://www.googleapis.com/auth/androidmanagement']))
    logging.info('Authentication succeeded.')
else:
    # FIXME: CHANGE THESE MAGIC NUMBERS;
    #        DO NOT HARD-CODE THEM IN A PUBLIC REPO!
    # This is a public OAuth config, you can use it to run this guide, but
    # please use different credentials when building your own solution.
    service_account_object = {
        'client_id':'882252295571-uvkkfelq073vq73bbq9cmr0rn8bt80ee.apps.googleusercontent.com',
        'client_secret': 'S2QcoBe0jxNLUoqnpeksCLxI',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://accounts.google.com/o/oauth2/token'
    }
    gcloud_project_id = input('What is the gcloud project ID (that runs your EMM service?): ')

    # To create and access resources,
    # you must authenticate with an account that has edit rights over your project.
    # To start the authentication flow, run the cell below.
    #
    # When you build a server-based solution, you should create a
    # service account so you don't need to authorize the access every time.
    #
    #     https://developers.google.com/android/management/service-account

    # Create the API client.
    androidmanagement = apiclient.discovery.build(
        'androidmanagement', 'v1',
        credentials=google_auth_oauthlib.flow.InstalledAppFlow.from_client_config(
            scopes=['https://www.googleapis.com/auth/androidmanagement'],
            client_config={'installed': service_account_object}
        ).run_console())

    print('\nAuthentication succeeded.')

# Get WPA2-PSK passphrases -- if any -- out of pypass.
for policy in json_config_object.get('policies', {}).values():
    for networkConfiguration in policy.get('openNetworkConfiguration', {}).get('NetworkConfigurations', []):
        if 'Passphrase' in networkConfiguration.get('WiFi', {}):
            logging.info('Asking pass(1) for WiFi PSK for %s', networkConfiguration['WiFi']['SSID'])
            networkConfiguration['WiFi']['Passphrase'] = pypass.PasswordStore().get_decrypted_password(
                f"android-wifi-PSK/{networkConfiguration['WiFi']['SSID']}").strip()

# Used later to revert this hack during dumping/caching.
# Symmetry with the above loop.
def redact_some_passphrases(device_or_policy_or_webapp: dict) -> None:  # DESTRUCTIVE
    policy = device_or_policy_or_webapp
    for networkConfiguration in policy.get('openNetworkConfiguration', {}).get('NetworkConfigurations', []):
        if 'Passphrase' in networkConfiguration.get('WiFi', {}):
            networkConfiguration['WiFi']['Passphrase'] = None


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

if 'enterprise_name' not in json_config_object:

    # Generate a signup URL where the enterprise admin can signup with a Gmail
    # account.
    signup_url = androidmanagement.signupUrls().create(
        projectId=gcloud_project_id,
        callbackUrl='https://storage.googleapis.com/android-management-quick-start/enterprise_signup_callback.html'
    ).execute()

    print('Please visit this URL to create an enterprise:', signup_url['url'])

    enterprise_token = input('Enter the code: ')

    # Complete the creation of the enterprise and retrieve the enterprise name.
    enterprise = androidmanagement.enterprises().create(
        projectId=gcloud_project_id,
        signupUrlName=signup_url['name'],
        enterpriseToken=enterprise_token,
        body={}
    ).execute()

    json_config_object['enterprise_name'] = enterprise['name']
    print('\nYour enterprise name is', json_config_object['enterprise_name'])


# Take note of the enterprise name so you can reuse it after you close this notebook.
# If you already have an enterprise, you can enter the enterprise name in the cell below and run the cell.


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

# Some settings have to be sent as JSON *encoded as a string*, e.g.
#
#  "URLBlocklist": "[\"*\", \"chrome://*\"]",
#
# This is FUCKING UNREADABLE, so as a workaround,
# let me write them as normal json,
# then convert it to a string here.
for chrome_policy in [
        # FIXME: this is ugly; use jsonpath?
        application['managedConfiguration']
        for android_policy in json_config_object['policies'].values()
        for application in android_policy.get('applications', [])
        if application['packageName'] == 'com.android.chrome'
        if 'managedConfiguration' in application]:
    for key in ('URLBlocklist', 'URLAllowlist', 'ManagedBookmarks'):
        if key not in chrome_policy:
            continue            # not present
        if isinstance(chrome_policy[key], str):
            continue            # already encoded into a string
        logging.debug('Double-json-ing com.android.chrome managedConfiguration %s', key)
        chrome_policy[key] = json.dumps(chrome_policy[key])

for policy_name, policy_body in json_config_object['policies'].items():
    # Example: "frobozz-DEADBE/policies/policy1"
    # FIXME: probably doesn't quote silly enterprise names properly.
    policy_path = f'{json_config_object["enterprise_name"]}/policies/{policy_name}'
    androidmanagement.enterprises().policies().patch(
        name=policy_path,
        body=policy_body).execute()


############################################################
## Create webapp pseudo-apps
############################################################

# Ref. https://colab.research.google.com/github/google/android-management-api-samples/blob/master/notebooks/web_apps.ipynb

# Google requires inline base64 PNG images.
# Let's just use URLs because fuck that.
# UPDATE: austlii.edu.au returns 200 to firefox, but 401 to python requests.
# Therefore, double fuck it --- I'll commit icons to git.
icon_dir = pathlib.Path('icons')
for webApp in json_config_object.get('webApps', []):
    if 'icons' not in webApp:
        icon_path = (icon_dir / webApp['title']).with_suffix('.png')
        if icon_path.exists():
            logging.debug('Slurping icon from disk: %s', icon_path)
            with icon_path.open(mode='rb') as f:
                webApp['icons'] = [{'imageData': base64.urlsafe_b64encode(f.read()).decode('UTF-8')}]

# Unlike policy, patch() won't implicitly create a webapp.
# Instead we must "PATCH if in LIST else CREATE".
# This mirrors SQL's "UPDATE if SELECT else INSERT".
old_webApps = androidmanagement.enterprises().webApps().list(
    parent=json_config_object['enterprise_name']).execute()['webApps']
for new_webApp in json_config_object['webApps']:
    # We assume the startUrl (not title) is unique.
    try:
        old_webApp, = [
            old_webApp
            for old_webApp in old_webApps
            if old_webApp['startUrl'] == new_webApp['startUrl']]
        # UGHHHHH, if we send a noop patch, the webapp version jumps, and play store pushes a "new" 50kB apk to every device.
        # Therefore if old_webApp == new_webApp, do nothing.
        # Except that old_webApp has some auto-populated fields, so
        # only compare startUrl/title/displayMode.
        # UPDATE: FIXME: when I upload a webApp['icons'], it isn't there when I query it back.  Is it broken during upload, or download?
        if all(old_webApp[k] == new_webApp[k]
               for k in new_webApp
               if k != 'icons'  # FIXME: is this permanently bugged, or what???
               ):
            logging.debug('Exists and unchanged, so call nothing')
            continue
        logging.debug('Exists, so call patch()')
        androidmanagement.enterprises().webApps().patch(
            name=old_webApp['name'],
            body=new_webApp).execute()
    except ValueError:
        logging.debug("Doesn't exist, so call create()")
        androidmanagement.enterprises().webApps().create(
            parent=json_config_object['enterprise_name'],
            body=new_webApp).execute()


############################################################
## Delete historical devices from the device list.
############################################################
def pages(
        resource: googleapiclient.discovery.Resource,  # e.g. androidmanagement.enterprises().devices()
        *args,
        **kwargs):
    "Given e.g. devices(), iterate over each page of responses."
    request = None
    while True:
        if request is None:     # first iteration through "while True"
            request = resource.list(*args, **kwargs)
        else:                   # subsequent iteration through "while True"
            request = resource.list_next(
                previous_request=request,
                previous_response=response)
        if request:           # on last page, list_next() returns None
            response = request.execute()
            yield response
        else:
            break


def merged_pages(
        resource: googleapiclient.discovery.Resource,  # e.g. androidmanagement.enterprises().devices()
        response_key: str,                             # e.g. "devices"
        *args,
        **kwargs):
    "Given e.g. devices(), iterate over each device (across multiple pages)."
    for page in pages(resource, *args, **kwargs):
        # Sanity check
        for k in page.keys():
            if k not in {response_key, 'nextPageToken'}:
                raise RuntimeError('Unexpected key', {k: page[k]})
        for record in page[response_key]:
            yield record

# If a device is re-enrolled, it becomes a new "device" with a new name.
# The old enrollment continues to exist under the old name.
# Delete any old enrollments that haven't already been deleted.
# Use set() to minimize the number of HTTP requests, since they're slow (urllib2 can't HTTP/3).
devices = list(
    merged_pages(
        # our arguments
        resource=androidmanagement.enterprises().devices(),
        response_key='devices',
        # google's arguments
        parent=json_config_object['enterprise_name']))
device_names_to_delete = (
    # All obsolete devices
    set(
        name
        for d in devices
        for name in d.get('previousDeviceNames', {}))
    &                  # set intersection -- name must be in both sets
    # All known devices
    set(d['name'] for d in devices))
for name in device_names_to_delete:
    androidmanagement.enterprises().devices().delete(
        name=name).execute()





######################################################################
## Do some queries
######################################################################
# Save to disk some notes about the current state, so
# it can be poked around at later with jq(1).
os.makedirs('cache', exist_ok=True)
with open('cache/API-androidmanagement-v1.json', mode='w') as f:
    resp = requests.get(
        # Either of these URLs works, and returns the same content.
        # This is the URL that apiclient.discovery.build() above talks to.
        'https://www.googleapis.com/discovery/v1/apis/androidmanagement/v1/rest'
        or
        # This is the URL that Google documentation told us to use.
        'https://androidmanagement.googleapis.com/$discovery/rest?version=v1')
    resp.raise_for_status()
    json.dump(
        resp.json(),
        f,
        sort_keys=True,
        indent=4)
    del resp


def my_json_dump(obj):
    path = pathlib.Path(f'cache/{obj["name"]}.json')
    os.makedirs(path.parent, exist_ok=True)
    with path.open('w') as f:
        json.dump(obj, f, sort_keys=True, indent=4)

for enterprise in merged_pages(
        # our arguments
        resource=androidmanagement.enterprises(),
        response_key='enterprises',
        # google's arguments
        projectId=gcloud_project_id):
    my_json_dump(enterprise)
    for response_key, resource in [
            ('devices', androidmanagement.enterprises().devices),
            ('policies', androidmanagement.enterprises().policies),
            ('webApps', androidmanagement.enterprises().webApps)]:
        for obj in merged_pages(
                # our arguments
                resource=resource(),
                response_key=response_key,
                # google's arguments
                parent=enterprise['name']):
            redact_some_passphrases(obj)  # DESTRUCTIVE
            my_json_dump(obj)

    # NOTE: because this is essentially EVERY app in Play Store,
    #       there is no list().
    #       Instead we ask for a single application by name.
    #       Get those names from current policies.
    #
    # NOTE: com.android.chrome's managedProperties is equivalent to
    #       https://www.chromium.org/administrators/policy-list-3
    if args.hurry_the_fuck_up:
        logging.debug('Skipping slow download of application stuff')
        continue
    for packageName in sorted(set(
            application['packageName']
            for policy in json_config_object['policies'].values()
            for application in policy.get('applications', [])
            if application['installType'] != 'BLOCKED')):
        try:
            my_json_dump(androidmanagement.enterprises().applications().get(
                name=f'{enterprise["name"]}/applications/{packageName}').execute())
        except googleapiclient.errors.HttpError as e:
            if e.resp.status == 404:
                logging.debug('App %s not in Play Store -- probably from F-Droid', packageName)
            else:
                raise


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

if args.hurry_the_fuck_up:
    logging.debug('Skipping everything else (probably just enrollment QR code)')
    exit()

# FIXME: this does enrollment for whatever the LAST POLICY IN THE LIST loop was.
# Since "policies" is a dict, the order is random!
# Move this crap inside the "for ... in policies" loop?
# https://developers.google.com/android/management/reference/rest/v1/enterprises.enrollmentTokens#EnrollmentToken
enrollment_token = androidmanagement.enterprises().enrollmentTokens().create(
    parent=json_config_object['enterprise_name'],
    body={"policyName": args.enrollment_policy_name or policy_name,
          'duration': f'{60 * 60 * 24 * 90}s',  # maximum duration (90 days, in seconds)
          }
).execute()


# Embed your enrollment token in either an enrollment link or a QR code, and then follow the provisioning instructions below.
if args.work_profile_mode:
    print('Please open this link on your device:',
          'https://enterprise.google.com/android/enroll?et=' + enrollment_token['value'])
else:
    # url = 'https://chart.googleapis.com/chart?' + urllib.parse.urlencode({
    #           'cht': 'qr',
    #           'chs': '500x500',
    #           'chl': enrollment_token['qrCode']})
    # print('Please visit this URL to scan the QR code:', url)
    # subprocess.check_call(['xdg-open', url])
    subprocess.run(['qrencode', '-tUTF8'],
                   check=True,
                   input=enrollment_token['qrCode'],
                   text=True)


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
