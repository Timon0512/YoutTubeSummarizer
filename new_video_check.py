"""Monitor a list of YouTube channels and analyse new uploads with Gemini.

The previous command line interface has been replaced with a simpler module level
configuration. Channels are specified via :data:`CHANNELS` and the module keeps
track of processed videos by reading and updating ``video_dict.json`` – the same
store that is used by the Streamlit front end. Whenever a new upload is detected
its transcript is analysed with Gemini through :func:`utils.extract_stock_sentiments`.
"""

from __future__ import annotations
from typing import Dict, List
import xml.etree.ElementTree as ET
import os
import pandas as pd
import requests
from utils import get_yt_transcript, save_to_json, get_llm_stock_rating, clean_and_parse_json, load_json_file
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_KEY")
rating_path = os.getenv("RATING_JSON_PATH", "rating.json")
transcipt_path = os.getenv("TRANSCRIT_JSON_PATH", "transcripts.json")

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

def create_df_table_from_rating():
    """

        ### 🧮 Calculation Rules
        1. Compute the **base_score** as the mean of the first three dimensions: base_score = (growth_outlook + profitability + market_conditions) / 3
        2. Weight this base score by **guidance_confidence**, and then add the tone sentiment to capture communication style: weighted_score = (base_score * guidance_confidence + tone) / 2
        3. Convert the result into a **0–100 Investment Recommendation Score**: investment_recommendation_score = round( (weighted_score + 1) / 2 * 100 , 1 )
        4. Based on the score, assign the **Recommendation** category:
            - 80–100 → **Buy**
            - 60–79 → **Hold / Accumulate**
            - 40–59 → **Neutral**
            - 20–39 → **Reduce / Sell**
            - 0–19 → **Strong Sell**

    """
    data = load_json_file(rating_path)
    rows = []
    for video_id, entries in data.items():
        for entry in entries:
            entry["video_id"] = video_id  # Video-ID als eigene Spalte
            rows.append(entry)

    df = pd.json_normalize(rows)
    df["base score"] = (df["Growth Outlook"] + df["Profitability"] + df["Market Conditions"]) / 3
    df["weighted score"] = (df["base score"] * df["Guidance"] + df["Sentiment"]) / 2
    df["investment_score"] = round( (df["weighted score"] + 1) / 2 * 100 , 1 )
    df.to_csv("investment_score.csv", sep=";")


def main():

    channels = [channel["id"] for channel in CHANNELS]
    transcript_dict = load_json_file(transcipt_path)
    rating_dict = load_json_file(rating_path)

    for channel in channels:
        latest_videos = fetch_latest_videos(channel, 2)
        ids = [video["id"] for video in latest_videos] # 'published': '2025-10-13T20:58:48+00:00'

        for video_id in ids:
            if video_id in transcript_dict.keys():
                transcript = transcript_dict.get(video_id, None)
                print(f"for video íd: {video_id} exists a transcript")

            else:
                print(f"downloading transcript for video íd: {video_id}")
                result = get_yt_transcript(video_id)
                if result["success"]:
                    transcript = result["data"]
                    transcript_dict[video_id] = transcript
                    save_to_json(transcript_dict, transcipt_path)
                else:
                    print(f"Transcript could not be downloaded for video id: {video_id}")
                    #Add Loggger later on
                    continue

            if video_id in rating_dict.keys():
                print(f"Rating for video id: {video_id} already exists")
                continue
            else:
                rating = get_llm_stock_rating(transcript=transcript, api_key=API_KEY)
                print(f"Rating is:")
                print(rating)
                cleaned_rating = clean_and_parse_json(rating)
                print(f"cleaned rating is:")
                print(cleaned_rating)
                rating_dict[video_id] = cleaned_rating
                save_to_json(rating_dict, rating_path)


if __name__ == "__main__":
    # main()
    create_df_table_from_rating()