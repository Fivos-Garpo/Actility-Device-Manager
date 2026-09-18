import requests
import time
import os
import json

TOKEN_URL = (
    "https://thingparkenterprise.eu.actility.com/"
    "thingpark/dx/admin/latest/api/oauth/token"
    "?renewToken=true&validityPeriod=12hours"
)

access_token = None
access_token_timestamp = 0

def load_credentials(file_name="credentials.txt"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, file_name)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Credentials file not found: {file_path}")
    credentials = {}
    with open(file_path, "r") as file:
        for line in file:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                credentials[key.strip()] = value.strip()
    if "client_id" not in credentials or "client_secret" not in credentials:
        raise ValueError("credentials.txt must contain both 'client_id' and 'client_secret'")
    return credentials["client_id"], credentials["client_secret"]

def save_token_to_file(token, timestamp, file_name="token.txt"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, file_name)
    try:
        with open(file_path, "w") as f:
            json.dump({"token": token, "timestamp": timestamp}, f)
    except Exception as e:
        print(f"Could not save token: {e}")

def load_token_from_file(file_name="token.txt"):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, file_name)
    if not os.path.exists(file_path):
        return None, 0
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        return data.get("token"), data.get("timestamp", 0)
    except Exception:
        return None, 0

def get_access_token(client_id, client_secret):
    payload = {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}
    headers = {"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    try:
        response = requests.post(TOKEN_URL, data=payload, headers=headers)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError(f"Unexpected response: {token_data}")
        timestamp = time.time()
        save_token_to_file(access_token, timestamp)
        return access_token, timestamp
    except requests.exceptions.RequestException as e:
        print(f"Error getting token: {e}")
        if e.response is not None:
            print("Server response:", e.response.text)
        return None, time.time()

def get_valid_token():
    global access_token, access_token_timestamp
    client_id, client_secret = load_credentials()
    token_validity = 43190
    if access_token and (time.time() - access_token_timestamp < token_validity):
        return access_token
    file_token, file_timestamp = load_token_from_file()
    if file_token and (time.time() - file_timestamp < token_validity):
        access_token, access_token_timestamp = file_token, file_timestamp
        return access_token
    access_token, access_token_timestamp = get_access_token(client_id, client_secret)
    return access_token

if __name__ == "__main__":
    token = get_valid_token()
    print("Current Token:", token)
