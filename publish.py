"""
Asali.Life Instagram & Facebook Auto-Publisher
Reads schedule.json, publishes any pending posts whose time has passed.
Runs via GitHub Actions cron.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
IG_ID = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
PAGE_ID = os.environ["META_PAGE_ID"]

SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "schedule.json")


def load_schedule():
    with open(SCHEDULE_FILE, "r") as f:
        return json.load(f)


def save_schedule(schedule):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f, indent=2)


def api_post(url, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def api_get(url):
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def publish_to_instagram(video_url, caption):
    """Create container, wait for processing, publish."""
    print(f"  [IG] Creating container...")
    result = api_post(
        f"https://graph.facebook.com/v25.0/{IG_ID}/media",
        {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": TOKEN,
        },
    )
    container_id = result["id"]
    print(f"  [IG] Container: {container_id}")

    # Poll for processing
    for i in range(120):
        status = api_get(
            f"https://graph.facebook.com/v25.0/{container_id}"
            f"?fields=status_code&access_token={TOKEN}"
        )
        code = status.get("status_code", "")
        if code == "FINISHED":
            print(f"  [IG] Processing complete")
            break
        elif code == "ERROR":
            print(f"  [IG] ERROR: {status}")
            return None
        time.sleep(5)
    else:
        print(f"  [IG] Timeout waiting for processing")
        return None

    # Publish
    pub = api_post(
        f"https://graph.facebook.com/v25.0/{IG_ID}/media_publish",
        {"creation_id": container_id, "access_token": TOKEN},
    )
    media_id = pub["id"]

    # Get permalink
    verify = api_get(
        f"https://graph.facebook.com/v25.0/{media_id}"
        f"?fields=permalink&access_token={TOKEN}"
    )
    permalink = verify.get("permalink", "")
    print(f"  [IG] Published: {permalink}")
    return permalink


def publish_to_facebook(video_url, caption):
    """Post video to Facebook Page."""
    print(f"  [FB] Publishing...")
    result = api_post(
        f"https://graph.facebook.com/v25.0/{PAGE_ID}/videos",
        {
            "file_url": video_url,
            "description": caption,
            "access_token": TOKEN,
        },
    )
    fb_id = result.get("id", "")
    print(f"  [FB] Published: {fb_id}")
    return fb_id


def main():
    schedule = load_schedule()
    now = datetime.now(timezone.utc)
    published_count = 0

    for post in schedule:
        if post["status"] != "pending":
            continue

        publish_time = datetime.fromisoformat(post["publish_time"]).astimezone(
            timezone.utc
        )

        if now >= publish_time:
            print(f"\n=== Publishing: {post['speaker']} ===")
            video_url = (
                f"https://drive.google.com/uc?export=download"
                f"&id={post['video_file_id']}"
            )

            ig_link = publish_to_instagram(video_url, post["caption"])
            fb_id = publish_to_facebook(video_url, post["caption"])

            if ig_link:
                post["status"] = "published"
                post["ig_permalink"] = ig_link
                post["fb_id"] = fb_id
                post["published_at"] = now.isoformat()
                published_count += 1
            else:
                post["status"] = "failed"
                print(f"  FAILED to publish {post['speaker']}")

    save_schedule(schedule)

    if published_count > 0:
        print(f"\nPublished {published_count} post(s)")
    else:
        print("No posts due right now")

    return published_count


if __name__ == "__main__":
    count = main()
    sys.exit(0)
