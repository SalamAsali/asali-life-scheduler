"""
Weekly token rotation.

Uses the long-lived USER token to fetch a fresh PAGE token from /me/accounts,
then updates the META_PAGE_ACCESS_TOKEN GitHub secret via the gh CLI.

If the USER token itself is within 14 days of expiry, opens a GitHub issue
asking the user to regenerate it from Graph API Explorer (this part can't be
fully automated without the App Secret).
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

USER_TOKEN = os.environ["META_USER_ACCESS_TOKEN"]
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


def main():
    # Check user token expiry first
    debug = api_get(
        f"https://graph.facebook.com/v25.0/debug_token"
        f"?input_token={USER_TOKEN}&access_token={USER_TOKEN}"
    )
    info = debug.get("data", {})
    if not info.get("is_valid"):
        open_issue(
            "Meta USER token is invalid — manual rotation needed",
            "The stored `META_USER_ACCESS_TOKEN` is no longer valid. "
            "Regenerate from https://developers.facebook.com/tools/explorer/ "
            "and update the GitHub secret. Until then, scheduled posts will fail.",
        )
        sys.exit(1)

    expires_at = info.get("expires_at", 0)
    days_left = (expires_at - time.time()) / 86400 if expires_at else 9999
    print(f"User token: {days_left:.1f} days until expiry")

    if 0 < days_left < 14:
        open_issue(
            f"Meta USER token expires in {days_left:.0f} days — rotate it",
            "Open Graph API Explorer, generate a new user token with the same scopes "
            "(`pages_show_list`, `business_management`, `instagram_basic`, "
            "`instagram_content_publish`, `pages_read_engagement`, `pages_manage_posts`, "
            "`instagram_manage_comments`, `instagram_manage_contents`, "
            "`instagram_manage_engagement`), then run:\n\n"
            "```\necho 'NEW_TOKEN' | gh secret set META_USER_ACCESS_TOKEN --repo "
            f"{REPO}\n```\n\nNext run of this workflow will derive a fresh page token from it.",
        )

    # Fetch fresh page token from /me/accounts
    accounts = api_get(
        f"https://graph.facebook.com/v25.0/me/accounts?access_token={USER_TOKEN}"
    )
    page = next((p for p in accounts.get("data", []) if p["id"] == PAGE_ID), None)
    if not page:
        print(f"FATAL: page {PAGE_ID} not in /me/accounts response")
        sys.exit(1)

    new_page_token = page["access_token"]

    # Verify it works
    verify = api_get(
        f"https://graph.facebook.com/v25.0/debug_token"
        f"?input_token={new_page_token}&access_token={new_page_token}"
    )
    if not verify.get("data", {}).get("is_valid"):
        print(f"FATAL: derived page token failed validation: {verify}")
        sys.exit(1)

    print(f"Derived fresh page token for {page['name']}")

    # Try to update the secret. The default workflow token can't write secrets,
    # so this only succeeds if REPO_PAT (fine-grained PAT, secrets:write) is set.
    # Falls back to opening an issue with the new token for manual paste.
    try:
        gh("secret", "set", "META_PAGE_ACCESS_TOKEN", "--repo", REPO, stdin=new_page_token)
        print("Updated META_PAGE_ACCESS_TOKEN secret")
    except subprocess.CalledProcessError as e:
        open_issue(
            "Fresh Meta page token ready — paste it into the secret",
            f"Couldn't auto-update the secret (`{e.stderr.strip()}`).\n\n"
            "Run locally:\n\n"
            "```\n"
            f"echo '{new_page_token}' | gh secret set META_PAGE_ACCESS_TOKEN --repo {REPO}\n"
            "```\n\n"
            "To make this automatic next time: create a fine-grained PAT at "
            "https://github.com/settings/tokens?type=beta with "
            "Secrets: read+write on this repo, save it as the `REPO_PAT` secret.",
        )


if __name__ == "__main__":
    main()
