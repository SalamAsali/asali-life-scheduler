"""
One-time: delete orphan FB videos from failed IG publishes, reset posts to pending.
"""
import json
import os
import urllib.error
import urllib.request

TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "schedule.json")

ORPHAN_FB_IDS = [
    "975110745252238",
    "1874906009856828",
    "1504321824810159",
    "1974060923470992",
    "4328481200753255",
    "1499904164918349",
]

def main():
    # Delete orphan FB posts
    for fb_id in ORPHAN_FB_IDS:
        try:
            req = urllib.request.Request(
                f"https://graph.facebook.com/v25.0/{fb_id}?access_token={TOKEN}",
                method="DELETE"
            )
            resp = urllib.request.urlopen(req)
            result = json.loads(resp.read())
            print(f"Deleted FB {fb_id}: {result}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"Failed to delete FB {fb_id}: {e} — {body}")

    # Reset failed posts to pending
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f)

    reset_count = 0
    for post in schedule:
        if post["status"] == "failed":
            post["status"] = "pending"
            post.pop("fb_id", None)
            post.pop("ig_permalink", None)
            post.pop("published_at", None)
            print(f"Reset {post['speaker']} to pending")
            reset_count += 1

    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f, indent=2)

    print(f"\nDone: deleted {len(ORPHAN_FB_IDS)} FB posts, reset {reset_count} posts to pending")

if __name__ == "__main__":
    main()
