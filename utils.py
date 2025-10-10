import requests
import xml.etree.ElementTree as ET
import json
import os
from datetime import datetime

# === KONFIGURATION ===
CHANNEL_ID = "UCyCBf6asf89aQJaSXuAuTsg"  # <-- YouTube Channel ID hier eintragen
LAST_CHECK_FILE = "last_videos.json"


def get_latest_videos(channel_id, limit=5):
    """Hole die letzten Videos eines YouTube-Kanals über RSS"""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    resp = requests.get(url)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "atom": "http://www.w3.org/2005/Atom"}

    videos = []
    for entry in root.findall("atom:entry", ns):
        video_id = entry.find("yt:videoId", ns).text
        title = entry.find("atom:title", ns).text
        published = entry.find("atom:published", ns).text
        videos.append({
            "id": video_id,
            "title": title,
            "published": published,
            "url": f"https://www.youtube.com/watch?v={video_id}"
        })
    return videos[:limit]


def load_last_known_videos():
    if not os.path.exists(LAST_CHECK_FILE):
        return []
    with open(LAST_CHECK_FILE, "r") as f:
        return json.load(f)


def save_last_known_videos(videos):
    with open(LAST_CHECK_FILE, "w") as f:
        json.dump([v["id"] for v in videos], f)


def check_for_new_videos():
    latest = get_latest_videos(CHANNEL_ID)
    old_ids = set(load_last_known_videos())
    new_videos = [v for v in latest if v["id"] not in old_ids]

    if new_videos:
        print(f"\n📺 Neue Videos gefunden ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}):")
        for v in new_videos:
            print(f" - {v['title']}: {v['url']}")
        save_last_known_videos(latest)
    else:
        print(f"{datetime.now().strftime('%H:%M:%S')} – Keine neuen Videos.")


if __name__ == "__main__":
    #check_for_new_videos()
    latest = get_latest_videos(CHANNEL_ID)
    print(len(latest))