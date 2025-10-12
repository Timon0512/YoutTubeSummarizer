"""Monitor a list of YouTube channels and analyse new uploads with Gemini.

The previous command line interface has been replaced with a simpler module level
configuration. Channels are specified via :data:`CHANNELS` and the module keeps
track of processed videos by reading and updating ``video_dict.json`` – the same
store that is used by the Streamlit front end. Whenever a new upload is detected
its transcript is analysed with Gemini through :func:`utils.extract_stock_sentiments`.
"""

from __future__ import annotations
from typing import Dict, List, MutableMapping, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET
import os
import requests
from utils import get_yt_transcript, save_to_video_dict, json_path, load_video_dict, return_stock_table, clean_and_parse_json
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_KEY")

# Channels to watch. Extend this list with additional IDs as needed.
CHANNELS: List[Dict[str, str]] = [
    {"id": "UCyCBf6asf89aQJaSXuAuTsg", "name": "Markus Koch"},
   # {"id": "UCzD0b1nXk1Zz4fZKZhSNyRw2", "name": "Marku2s Koch"},
]

def fetch_latest_videos(channel_id: str, limit: int = 5) -> List[Dict[str, str]]:
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
                "published": published,
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }
        )

    return videos

def main():

    channels = [channel["id"] for channel in CHANNELS]
    video_dict = load_video_dict(json_path)

    for channel in channels:
        latest_videos = fetch_latest_videos(channel, 1)
        ids = [video["id"] for video in latest_videos]

        for video_id in ids:
            if video_id in video_dict.keys():
                print(f"{id} is in keys")
            else:
                print(f"{video_id} is not in keys")
                result = get_yt_transcript(video_id)
                if result["success"]:
                    #save transcript to json
                    video_dict["video_id"] = {"transcript": result["data"],
                                            "summary": {},
                                            "table": [],
                                            }
                    save_to_video_dict(json_path)
                    table = return_stock_table(transcript=result["data"], api_key=API_KEY)
                    cleaned_table = clean_and_parse_json(table)
                    print(cleaned_table)
                    video_dict["video_id"]["table"] = cleaned_table
                    save_to_video_dict(json_path)
                else:
                    #add logging later on
                    continue

                continue


if __name__ == "__main__":
    main()