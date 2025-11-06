from __future__ import annotations
from typing import Dict, List
import xml.etree.ElementTree as ET
import os
import requests
from utils import get_yt_transcript, save_to_json, load_json_file
from dotenv import load_dotenv
from googleapiclient.discovery import build
from datetime import datetime

load_dotenv()
API_KEY = os.getenv("API_KEY")
GOOGLE_API = os.getenv("GOOGLE_API")
rating_path = os.path.join(os.path.dirname(__file__), "rating.json")
transcipt_path = os.path.join(os.path.dirname(__file__), "transcripts.json")

SOURCES: list[dict[str, str]] = [
    #{"type": "channel", "id": "UCyCBf6asf89aQJaSXuAuTsg", "name": "Markus Koch"},
    {"type": "playlist", "id": "PL6P5rY8mrhqrhVgc_pkSOlRLpuGW3CpJ3", "name": "Alles auf Aktien"},
    #{"type": "playlist", "id": "PLhYtU24OgOhpTsGgNZU3ZyyE98KgOPF0v", "name": "Markus Koch"},
]

def fetch_latest_videos_from_channel(channel_id: str, limit: int = 5) -> List[Dict[str, str]]:
    """Fetch metadata for the latest ``limit`` videos of a channel.

    The function relies on the public YouTube RSS endpoint and therefore does not
    require an API key.
    """

    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.text)
    ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "atom": "http://www.w3.org/2005/Atom"}

    videos: List[Dict[str, str]] = []
    for entry in root.findall("atom:entry", ns)[:limit]:
        video_id = entry.find("yt:videoId", ns).text  # type: ignore[union-attr]
        title = entry.find("atom:title", ns).text or ""
        published = entry.find("atom:published", ns).text or ""
        videos.append(
            {
                "id": video_id,
                "title": title,
                "date": published,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "description": None
            }
        )

    return videos

def fetch_latest_videos_from_playlist(playlist_id: str, lastResults: int = 5) -> List[Dict[str, str]]:
    youtube = build("youtube", "v3", developerKey=GOOGLE_API)

    playlist_response = youtube.playlistItems().list(
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=lastResults,
    ).execute()

    videos: List[Dict[str, str]] = []

    for item in playlist_response["items"]:
        video_id = item["contentDetails"]["videoId"]
        date = item["contentDetails"]["videoPublishedAt"]
        title = item["snippet"]["title"]
        description = item["snippet"]["description"]

        videos.append(
            {
                "id": video_id,
                "title": title,
                "date": date,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "description": description
            }
        )
    return videos

def process_videos(source_name, video_fetcher, source_id, transcript_path):
    transcript_dict = load_json_file(transcript_path)
    latest_videos = video_fetcher(source_id)

    for video in latest_videos:
        video_id = video["id"]
        # --- Transcript Handling ---
        if video_id in transcript_dict:
            print(f"Transcript already exists for {video_id}")
            # transcript = transcript_dict[video_id].get("transcript") # Unused because I removed the automatic rating
        else:
            print(f"Downloading transcript for {video_id}")
            result = get_yt_transcript(video_id)
            if not result["success"]:
                print(f"Transcript failed for {video_id}")
                continue

            transcript = result["data"]
            video_entry = {"name": source_name,
                           **video,
                           "processed_on": datetime.now(),
                           "transcript": transcript}
            transcript_dict[video_id] = video_entry
            save_to_json(transcript_dict, transcript_path)

    print(f"✅ Finished processing {source_name}")


def main():

    for src in SOURCES:
        src_type = src["type"]
        src_id = src["id"]
        src_name = src["name"]

        if src_type == "channel":
            print(f"Channel")
            fetcher = lambda sid: fetch_latest_videos_from_channel(sid, 1)
        elif src_type == "playlist":
            print(f"Playlist")
            fetcher = lambda sid: fetch_latest_videos_from_playlist(sid, lastResults=6)
        else:
            print(f"Unbekannter Typ: {src_type}")
            continue


        print(f"\n=== Verarbeite {src_type}: {src_name} ===")
        process_videos(
            source_name=src_name,
            video_fetcher=fetcher,
            source_id=src_id,
            transcript_path=transcipt_path,
        )


if __name__ == "__main__":
    main()