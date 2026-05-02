"""
GTM OAuth 2.0 authentication handler.
Saves tokens locally to token.json and auto-refreshes on expiry.
"""

import json
import os
from urllib.parse import urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

CONFIG_FILE = "config.json"


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(
            f"{CONFIG_FILE} not found. Copy config.json template and fill in your credentials."
        )
    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_credentials() -> Credentials:
    """
    Returns valid credentials, running the OAuth flow if needed.
    Tokens are persisted to token.json and refreshed automatically.
    """
    config = load_config()
    scopes = config["scopes"]
    token_file = config.get("token_file", "token.json")

    creds = None

    # Load existing token if available
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)

    # Refresh or run full OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing access token...")
            creds.refresh(Request())
        else:
            print("Starting OAuth 2.0 flow — a browser window will open.")
            client_config = {
                "installed": {
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "redirect_uris": [config.get("redirect_uri", "http://localhost:8080")],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, scopes)
            redirect_uri = config.get("redirect_uri", "http://localhost:8080")
            creds = flow.run_local_server(
                port=urlparse(redirect_uri).port or 8080,
                prompt="consent",
                access_type="offline",
            )

        # Persist the token for future runs
        with open(token_file, "w") as f:
            f.write(creds.to_json())
        print(f"Token saved to {token_file}")

    return creds


def get_gtm_service():
    """Returns an authenticated GTM API service client."""
    creds = get_credentials()
    return build("tagmanager", "v2", credentials=creds)


if __name__ == "__main__":
    print("Testing authentication...")
    service = get_gtm_service()
    accounts = service.accounts().list().execute()
    account_list = accounts.get("account", [])
    if account_list:
        print(f"Authenticated. Found {len(account_list)} GTM account(s):")
        for acct in account_list:
            print(f"  - {acct['name']} (ID: {acct['accountId']})")
    else:
        print("Authenticated successfully. No GTM accounts found for this user.")
