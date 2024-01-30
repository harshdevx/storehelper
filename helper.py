import os
import json
import requests
import time
import jwt
import subprocess
import yaml
from pathlib import Path
from dotenv import dotenv_values

env_dir = os.path.join(os.getcwd())
env_file = os.path.join(env_dir, ".env")
config = dotenv_values(env_file)

# variable declaration
vault_token: str

project_dir = Path(__file__).parents[1]

def create_apple_build():
    os.system("/Volumes/devdisk/apps/flutter-3.10.6/bin/flutter build ipa --target-platform android-arm64")

def create_google_build():
    os.system("/Volumes/devdisk/apps/flutter-3.10.6/bin/flutter build ipa --release -v")

# apple auto upload
def process_appstore(appstore_creds):
    ipa_file = f"{project_dir}/build/ios/ipa/Kliqit\ Group\ Counter.ipa"
    command = f"xcrun altool --upload-app --type ios -f {ipa_file} --apiKey {appstore_creds.get('appstore_api_key')} --apiIssuer {appstore_creds.get('appstore_issuer_id')}"
    os.system(command)

# google auto upload
def process_playstore(googlestore_creds):
    # google variables
    playstore_client_email = googlestore_creds.get("client_email")
    playstore_private_key = googlestore_creds.get("private_key")
    playstore_token_uri = googlestore_creds.get("token_uri")
    package_name: str = "io.kliqit.app"

    iat = time.time()
    exp = iat + 600

    jwt_header: dict = {
        "alg": "RS256",
        "typ": "JWT"
    }

    jwt_claims: dict = {
        "iss": playstore_client_email,
        "iat": iat,
        "exp": exp,
        "scope": config.get("GOOGLE_PUBLISHER_SCOPE_ENDPOINT"),
        "aud": playstore_token_uri
    }

    jwt_token = jwt.encode(payload=jwt_claims, headers=jwt_header, key=playstore_private_key)

    auth_headers: dict = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    query_parameters = f"grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion={jwt_token}"

    api_auth_response = requests.post(url=f"{playstore_token_uri}?{query_parameters}", headers=auth_headers)
    if api_auth_response.ok: 
        google_developer_api_access_token = api_auth_response.json().get("access_token")

    google_publisher_api_headers: dict = {
        "Authorization": f"Bearer {google_developer_api_access_token}"
    }

    # try:
    # create edits
    edits_url = f"{config.get('GOOGLE_PUBLISHER_API')}/androidpublisher/v3/applications/{package_name}/edits"
    edits_response = requests.post(url=edits_url,headers=google_publisher_api_headers)
    edit_id = edits_response.json().get("id")
    
    # upload logic
    # aab_file = open(f"{project_dir}/{config.get('APPBUNDLE_PATH')}", 'rb')
    aab_file = f"{project_dir}/{config.get('APPBUNDLE_PATH')}"
    upload_url = f"{config.get('GOOGLE_PUBLISHER_API')}/upload/androidpublisher/v3/applications/{package_name}/edits/{edit_id}/bundles?uploadType=media"
    # upload_response: dict = os.system(f'curl --header "Authorization: Bearer {google_developer_api_access_token}" --header "Content-Type: application/octet-stream" --progress-bar --request POST --upload-file {aab_file} {upload_url}')
    subprocess_response = subprocess.check_output(f'curl --header "Authorization: Bearer {google_developer_api_access_token}" --header "Content-Type: application/octet-stream" --request POST --upload-file {aab_file} {upload_url}', shell=True)

    upload_response = json.loads(subprocess_response.decode('utf-8').replace("'", '"'))
    
    # update track
    print("running tracks")
    with open(f"{project_dir}/pubspec.yaml", "r") as stream:
        try:
            version_name_suffix = str(yaml.safe_load(stream)["version"]).split("+")[0]
        except yaml.YAMLError as exc:
            print(exc)
    tracks_url = f"{config.get('GOOGLE_PUBLISHER_API')}/androidpublisher/v3/applications/{package_name}/edits/{edit_id}/tracks/{config.get('TRACK')}"
    track_body: dict = {
        "track": "production",
        "releases": [
            {
                "name": f"{str(upload_response.get('versionCode'))} ({version_name_suffix})",
                "versionCodes": [ str(upload_response.get("versionCode")) ],
                "status": "completed"
            }
        ]
    }
    google_publisher_api_headers.update({"Content-Type": "application/json"})
    track_response = requests.put(url=tracks_url, headers=google_publisher_api_headers, data=json.dumps(track_body))

    if track_response.ok: 
        commits_url = f"{edits_url}/{edit_id}:commit"
        print("running commit")
        commits_response = requests.post(url=commits_url, headers=google_publisher_api_headers)
        if commits_response.ok:
            print("completed commits") 
            print(commits_response.json())
        else:
            print(commits_response.json())
    # except Exception as e:
    #     print(f"Exception: {e}")
    
    
def main():
    
    hv_headers: dict = {
        "Content-Type": "application/json",
    }
    hv_payload: dict = {
        "password": config.get("VAULT_PASSWORD")
    }
    hv_response = requests.post(url=f'{config.get("VAULT_URL")}/auth/userpass/login/{config.get("VAULT_USERNAME")}', 
                data=json.dumps(hv_payload), headers=hv_headers)
    if hv_response.ok:
        vault_token = hv_response.json().get('auth').get('client_token')
    
    request_headers: dict = {
        "Content-Type": "application/json",
        "X-VAULT-TOKEN": vault_token
    }

    appstore_creds_response = requests.get(url=f'{config.get("VAULT_URL")}/kliqit/data/apple-developer-api', headers=request_headers)

    if appstore_creds_response.ok: 
        appstore_creds: dict = {
            "appstore_api_key": appstore_creds_response.json().get("data").get("data").get("appstore_api_key"),
            "appstore_issuer_id": appstore_creds_response.json().get("data").get("data").get("appstore_issuer_id")
        }
        create_apple_build()
        process_appstore(appstore_creds)
        print("processing apple auto deploy")


    googlestore_creds = requests.get(url=f'{config.get("VAULT_URL")}/kliqit/data/google-developer-api', headers=request_headers)

    if googlestore_creds.ok: 
        # create new google build
        create_google_build()
        process_playstore(googlestore_creds.json().get("data").get("data"))
        print("processing google auto deploy")

main()
