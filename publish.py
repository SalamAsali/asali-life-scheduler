"""
Asali.Life Instagram & Facebook Auto-Publisher
Reads schedule.json, publishes any pending posts whose time has passed.
Runs via GitHub Actions cron. Supports both video reels and image posts.
Optionally syncs status back to Notion if NOTION_API_KEY is set.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
IG_ID = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
PAGE_ID = os.environ["META_PAGE_ID"]
NOTION_TOKEN = os.environ.get("NOTION_API_KEY", "")
REPO = "SalamAsali/asali-life-scheduler"

SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "schedule.json")
MAX_PER_RUN = 1  # 3 cron runs/day × 1 = 3 posts/day


def load_schedule():
    with open(SCHEDULE_FILE, "r") as f:
        return json.load(f)


def save_schedule(schedule):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f, indent=2)


def api_post(url, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  API POST error {e.code}: {body}")
        raise


def api_get(url):
    req = urllib.request.Request(url)
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  API GET error {e.code}: {body}")
        raise


def preflight_token():
    """Verify Meta token validity; warn if expiring soon, fail loudly if dead."""
    try:
        info = api_get(
            f"https://graph.facebook.com/v25.0/debug_token"
            f"?input_token={TOKEN}&access_token={TOKEN}"
        )
        data = info.get("data", {})
    except Exception as e:
        print(f"FATAL: token preflight failed: {e}")
        sys.exit(1)

    if not data.get("is_valid"):
        print(f"FATAL: META_PAGE_ACCESS_TOKEN is invalid: {data}")
        sys.exit(1)

    expires_at = data.get("expires_at", 0)
    if expires_at:
        days_left = (expires_at - time.time()) / 86400
        if days_left < 0:
            print(f"FATAL: token expired {-days_left:.1f} days ago")
            sys.exit(1)
        if days_left < 7:
            print(f"WARNING: token expires in {days_left:.1f} days — rotate soon")
        else:
            print(f"[OK] Token valid, expires in {days_left:.1f} days")
    else:
        print("[OK] Token valid (no expiry)")


def get_media_url(post):
    """Get the public URL for the media file."""
    if "video_file_id" in post:
        return f"https://drive.google.com/uc?export=download&id={post['video_file_id']}"
    elif "video_file" in post:
        return f"https://raw.githubusercontent.com/{REPO}/main/videos/{post['video_file']}"
    elif "image_file" in post:
        return f"https://raw.githubusercontent.com/{REPO}/main/images/{post['image_file']}"
    return None


def publish_to_instagram(media_url, caption, media_type="REELS"):
    """Create container, poll for processing, publish."""
    print(f"  [IG] Creating container ({media_type})...")

    params = {"caption": caption, "access_token": TOKEN}
    if media_type == "REELS":
        params["media_type"] = "REELS"
        params["video_url"] = media_url
    else:
        params["image_url"] = media_url

    try:
        result = api_post(f"https://graph.facebook.com/v25.0/{IG_ID}/media", params)
        container_id = result["id"]
        print(f"  [IG] Container: {container_id}")
    except Exception as e:
        print(f"  [IG] Container creation failed: {e}")
        return None

    for _ in range(120):
        try:
            status = api_get(
                f"https://graph.facebook.com/v25.0/{container_id}"
                f"?fields=status_code&access_token={TOKEN}"
            )
        except Exception as e:
            print(f"  [IG] Status check failed: {e}")
            return None
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

    try:
        pub = api_post(
            f"https://graph.facebook.com/v25.0/{IG_ID}/media_publish",
            {"creation_id": container_id, "access_token": TOKEN},
        )
        media_id = pub["id"]
    except Exception as e:
        print(f"  [IG] Publish failed: {e}")
        return None

    try:
        verify = api_get(
            f"https://graph.facebook.com/v25.0/{media_id}"
            f"?fields=permalink&access_token={TOKEN}"
        )
        permalink = verify.get("permalink", "")
    except Exception:
        permalink = f"(published but couldn't verify, media_id={media_id})"

    print(f"  [IG] Published: {permalink}")
    return permalink


def publish_to_facebook(media_url, caption, media_type="REELS"):
    """Post to Facebook Page."""
    print(f"  [FB] Publishing...")
    try:
        if media_type == "REELS":
            result = api_post(
                f"https://graph.facebook.com/v25.0/{PAGE_ID}/videos",
                {"file_url": media_url, "description": caption, "access_token": TOKEN},
            )
        else:
            result = api_post(
                f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos",
                {"url": media_url, "message": caption, "access_token": TOKEN},
            )
        fb_id = result.get("id", "")
        print(f"  [FB] Published: {fb_id}")
        return fb_id
    except Exception as e:
        print(f"  [FB] Failed: {e}")
        return None


def notion_mark_published(page_id, ig_permalink, fb_id):
    """Patch the Notion page: Status=Published, store links. No-op if NOTION_API_KEY unset."""
    if not NOTION_TOKEN or not page_id:
        return

    url = f"https://api.notion.com/v1/pages/{page_id}"
    body = {
        "properties": {
            "Status": {"status": {"name": "Published"}},
            "Instagram URL": {"url": ig_permalink or None},
            "Facebook ID": {"rich_text": [{"text": {"content": fb_id or ""}}]},
            "Published At": {
                "date": {"start": datetime.now(timezone.utc).isoformat()}
            },
        }
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req)
        print(f"  [Notion] Updated page {page_id[:8]}...")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [Notion] Update failed {e.code}: {body}")


def main():
    preflight_token()

    schedule = load_schedule()
    now = datetime.now(timezone.utc)
    published_count = 0

    for post in schedule:
        if post["status"] != "pending":
            continue
        if published_count >= MAX_PER_RUN:
            break

        publish_time = datetime.fromisoformat(post["publish_time"]).astimezone(
            timezone.utc
        )

        if now >= publish_time:
            print(f"\n=== Publishing: {post['speaker']} ===")
            media_url = get_media_url(post)
            if not media_url:
                print(f"  No media URL found, skipping")
                continue

            media_type = post.get("media_type", "REELS")
            ig_link = publish_to_instagram(media_url, post["caption"], media_type)
            fb_id = publish_to_facebook(media_url, post["caption"], media_type)

            if ig_link:
                post["status"] = "published"
                post["ig_permalink"] = ig_link
                post["fb_id"] = fb_id
                post["published_at"] = now.isoformat()
                notion_mark_published(post.get("notion_page_id"), ig_link, fb_id)
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
