"""
One-time: delete posts from the May 25 bulk publish, reset to pending, reschedule.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
IG_ID = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "schedule.json")

# Posts bulk-published on 2026-05-25T13:
BULK_IDS = ["tony-robbins", "gary-vee", "barack-obama", "mike-tyson", "eminem", "serena-williams"]

# IG media IDs and FB post IDs from that run
IG_MEDIA_IDS = [
    "18108360635310886", "18118098895781746", "17872789608505046",
    "18184529860380792", "18093617636221370", "18360098107231221",
]
FB_POST_IDS = [
    "935650109520517", "2146174532841439", "1329169792421708",
    "1346091030756270", "1763480801479086", "1496580185269048",
]


def api_delete(url):
    req = urllib.request.Request(url, method="DELETE")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def main():
    # Delete from IG
    for mid in IG_MEDIA_IDS:
        try:
            result = api_delete(f"https://graph.facebook.com/v25.0/{mid}?access_token={TOKEN}")
            print(f"[IG] Deleted {mid}: {result}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[IG] Failed {mid}: {e} — {body}")

    # Delete from FB
    for fid in FB_POST_IDS:
        try:
            result = api_delete(f"https://graph.facebook.com/v25.0/{fid}?access_token={TOKEN}")
            print(f"[FB] Deleted {fid}: {result}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[FB] Failed {fid}: {e} — {body}")

    # Reset and reschedule
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f)

    for post in schedule:
        if post["id"] in BULK_IDS:
            post["status"] = "pending"
            for key in ["ig_permalink", "fb_id", "published_at"]:
                post.pop(key, None)
            print(f"Reset {post['speaker']} to pending")

    # Reschedule all pending at 3/day starting tomorrow
    edt = timezone(timedelta(hours=-4))
    tomorrow = datetime(2026, 5, 26, 0, 0, 0, tzinfo=edt)
    time_slots = [timedelta(hours=11), timedelta(hours=17), timedelta(hours=21)]

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

    print(f"\nDone: reset {len(BULK_IDS)} posts, rescheduled {len(pending)} pending")


if __name__ == "__main__":
    main()
