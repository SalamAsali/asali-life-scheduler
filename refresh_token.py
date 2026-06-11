"""
Weekly token health check + auto-extension.

With the App Secret available, this self-heals indefinitely:
  1. Debug-checks the user token. If it's invalid, opens an alert issue.
  2. If user token is within 14 days of expiry (or already long-lived),
     calls fb_exchange_token to mint a fresh ~60-day user token.
  3. Derives a page token via /me/accounts.
  4. Updates GitHub secrets.

Required env: META_USER_ACCESS_TOKEN, META_APP_ID, META_APP_SECRET, META_PAGE_ID, GH_TOKEN
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_TOKEN = os.environ["META_USER_ACCESS_TOKEN"]
APP_ID = os.environ["META_APP_ID"]
APP_SECRET = os.environ["META_APP_SECRET"]
PAGE_ID = os.environ["META_PAGE_ID"]
REPO = "SalamAsali/asali-life-scheduler"


def api_get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def gh(*args, stdin=None):
    return subprocess.run(
        ["gh", *args],
        input=stdin,
        text=True,
        check=True,
        capture_output=True,
    )


def open_issue(title, body):
    try:
        gh("issue", "create", "--repo", REPO, "--title", title, "--body", body)
        print(f"  Opened issue: {title}")
    except subprocess.CalledProcessError as e:
        print(f"  Failed to open issue: {e.stderr}")


def exchange_for_long_lived(token):
    """Mint a fresh long-lived user token via fb_exchange_token."""
    params = urllib.parse.urlencode({
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": token,
    })
    url = f"https://graph.facebook.com/v25.0/oauth/access_token?{params}"
    return api_get(url)["access_token"]


def set_secret(name, value):
    try:
        gh("secret", "set", name, "--repo", REPO, stdin=value)
        print(f"  Updated {name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Failed to update {name}: {e.stderr.strip()}")
        return False


def main():
    # Check user token validity
    debug = api_get(
        f"https://graph.facebook.com/v25.0/debug_token"
        f"?input_token={USER_TOKEN}&access_token={USER_TOKEN}"
    )
    info = debug.get("data", {})
    if not info.get("is_valid"):
        open_issue(
            "Meta USER token invalid — manual rotation needed",
            "The stored `META_USER_ACCESS_TOKEN` failed validation. This usually "
            "means the FB password was changed or the app permissions were revoked.\n\n"
            "Recovery: regenerate a short-lived token from "
            "https://developers.facebook.com/tools/explorer/ and run:\n\n"
            "```\necho 'NEW_SHORT_TOKEN' | gh secret set META_USER_ACCESS_TOKEN --repo "
            f"{REPO}\n```\n\nThen manually trigger the refresh workflow — it'll exchange "
            "for long-lived and roll forward.",
        )
        sys.exit(1)

    expires_at = info.get("expires_at", 0)
    days_left = (expires_at - time.time()) / 86400 if expires_at else 9999
    print(f"User token: {days_left:.1f} days until expiry")

    # Refresh proactively: exchange whenever <14d left or expiry < 60d
    # (60d cap covers the case where a "permanent" token might still rotate)
    if days_left < 14 or (0 < days_left < 60):
        print("Exchanging for fresh long-lived user token...")
        new_user_token = exchange_for_long_lived(USER_TOKEN)
        set_secret("META_USER_ACCESS_TOKEN", new_user_token)
        token_for_pages = new_user_token
    else:
        token_for_pages = USER_TOKEN

    # Derive page token
    accounts = api_get(
        f"https://graph.facebook.com/v25.0/me/accounts?access_token={token_for_pages}"
    )
    page = next((p for p in accounts.get("data", []) if p["id"] == PAGE_ID), None)
    if not page:
        print(f"FATAL: page {PAGE_ID} not in /me/accounts response")
        sys.exit(1)

    new_page_token = page["access_token"]

    verify = api_get(
        f"https://graph.facebook.com/v25.0/debug_token"
        f"?input_token={new_page_token}&access_token={new_page_token}"
    )
    if not verify.get("data", {}).get("is_valid"):
        print(f"FATAL: derived page token failed validation: {verify}")
        sys.exit(1)

    print(f"Derived fresh page token for {page['name']}")

    if not set_secret("META_PAGE_ACCESS_TOKEN", new_page_token):
        open_issue(
            "Fresh Meta page token ready — paste it into the secret",
            "Couldn't auto-update the secret (likely because `REPO_PAT` isn't configured).\n\n"
            "Create a fine-grained PAT at https://github.com/settings/tokens?type=beta "
            "with Secrets: read+write on this repo, save it as `REPO_PAT` secret. "
            "After that, future refresh runs are fully automatic.",
        )


if __name__ == "__main__":
    main()
