"""
One-time cleanup: delete bulk-published posts from IG + FB, reset them in schedule.json.
Posts will be rescheduled at 3/day starting tomorrow.
"""
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "schedule.json")

# Posts that were bulk-published on 2026-05-22T17:19 and need to be deleted
BULK_PUBLISHED_IDS = [
    "tony-robbins", "gary-vee", "barack-obama", "mike-tyson",
    "eminem", "serena-williams", "lebron-james", "tom-brady", "tupac"
]


def api_delete(url):
    req = urllib.request.Request(url, method="DELETE")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def delete_ig_post(permalink):
    """Extract media ID from permalink and delete it."""
    # Get media ID from permalink using oEmbed
    media_id = permalink.rstrip("/").split("/")[-1]
    # We need the numeric ID - get it from the Graph API
    try:
        url = f"https://graph.facebook.com/v25.0/ig_hashtag_search?q=test&access_token={TOKEN}"
        # Actually, we stored the IG permalink but not the media_id.
        # We need to look it up via the permalink
        lookup_url = (
            f"https://graph.facebook.com/v25.0/ig_media"
            f"?fields=id&access_token={TOKEN}"
        )
        # The container ID was printed in logs but not stored.
        # Let's use the IG user media endpoint to find and delete.
        return None
    except Exception as e:
        print(f"  Error looking up: {e}")
        return None


def delete_fb_post(fb_id):
    """Delete a Facebook post by ID."""
    try:
        result = api_delete(
            f"https://graph.facebook.com/v25.0/{fb_id}?access_token={TOKEN}"
        )
        print(f"  [FB] Deleted {fb_id}: {result}")
        return True
    except Exception as e:
        print(f"  [FB] Delete failed for {fb_id}: {e}")
        return False


def main():
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f)

    ig_user_id = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]

    # Get all recent media from the IG account
    print("Fetching recent IG media...")
    try:
        url = (
            f"https://graph.facebook.com/v25.0/{ig_user_id}/media"
            f"?fields=id,permalink,timestamp&limit=20&access_token={TOKEN}"
        )
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req)
        media_list = json.loads(resp.read()).get("data", [])
        print(f"  Found {len(media_list)} recent posts")
    except Exception as e:
        print(f"  Failed to fetch media: {e}")
        media_list = []

    # Build permalink -> media_id map
    permalink_to_id = {}
    for m in media_list:
        permalink_to_id[m.get("permalink", "")] = m["id"]

    # Delete each bulk-published post
    deleted_count = 0
    for post in schedule:
        if post["id"] not in BULK_PUBLISHED_IDS:
            continue

        print(f"\n=== Cleaning up: {post['speaker']} ===")

        # Delete from Instagram
        ig_link = post.get("ig_permalink", "")
        ig_media_id = permalink_to_id.get(ig_link)
        if ig_media_id:
            try:
                result = api_delete(
                    f"https://graph.facebook.com/v25.0/{ig_media_id}?access_token={TOKEN}"
                )
                print(f"  [IG] Deleted {ig_media_id}: {result}")
            except Exception as e:
                print(f"  [IG] Delete failed: {e}")
        else:
            print(f"  [IG] Could not find media ID for {ig_link}")

        # Delete from Facebook
        fb_id = post.get("fb_id")
        if fb_id:
            delete_fb_post(fb_id)

        # Reset post status
        post["status"] = "pending"
        for key in ["ig_permalink", "fb_id", "published_at"]:
            post.pop(key, None)
        deleted_count += 1

    # Reschedule: 3 posts per day starting tomorrow at 11AM, 5PM, 9PM EDT
    print("\n=== Rescheduling posts ===")
    edt = timezone(timedelta(hours=-4))
    tomorrow = datetime(2026, 5, 23, 0, 0, 0, tzinfo=edt)
    time_slots = [
        timedelta(hours=11),  # 11 AM EDT
        timedelta(hours=17),  # 5 PM EDT
        timedelta(hours=21),  # 9 PM EDT
    ]

    # Collect all pending posts in order
    pending = [p for p in schedule if p["status"] == "pending"]
    slot_idx = 0
    day_offset = 0

    for post in pending:
        new_time = tomorrow + timedelta(days=day_offset) + time_slots[slot_idx]
        post["publish_time"] = new_time.isoformat()
        print(f"  {post['speaker']:25s} -> {new_time.strftime('%Y-%m-%d %I:%M %p EDT')}")
        slot_idx += 1
        if slot_idx >= 3:
            slot_idx = 0
            day_offset += 1

    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f, indent=2)

    print(f"\nDone: deleted {deleted_count} posts, rescheduled {len(pending)} pending posts")


if __name__ == "__main__":
    main()
