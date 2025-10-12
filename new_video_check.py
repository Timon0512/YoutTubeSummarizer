"""Monitor a list of YouTube channels and analyse new uploads with Gemini.

The previous command line interface has been replaced with a simpler module level
configuration. Channels are specified via :data:`CHANNELS` and the module keeps
track of processed videos by reading and updating ``video_dict.json`` – the same
store that is used by the Streamlit front end. Whenever a new upload is detected
its transcript is analysed with Gemini through :func:`utils.extract_stock_sentiments`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, MutableMapping, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET

import requests
from youtube_transcript_api import YouTubeTranscriptApi, _errors

from utils import extract_stock_sentiments, json_path


# Channels to watch. Extend this list with additional IDs as needed.
CHANNELS: List[Dict[str, str]] = [
    {"id": "UCzD0b1nXk1Zz4fZKZhSNyRw", "name": "Markus Koch"},
]

# Reuse the same JSON file as the Streamlit app so that processed videos only
# need to be analysed once.
VIDEO_STORE_PATH = json_path


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


def _fetch_transcript(video_id: str) -> str:
    """Return the transcript text for ``video_id`` or an empty string."""

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
    except (
        _errors.TranscriptsDisabled,
        _errors.NoTranscriptFound,
        _errors.NotTranslatable,
        _errors.VideoUnavailable,
        _errors.CouldNotRetrieveTranscript,
        _errors.YouTubeTranscriptApiException,
    ):
        return ""

    return " ".join(segment.get("text", "") for segment in transcript)


def load_video_store(path: str = VIDEO_STORE_PATH) -> Dict[str, Dict[str, object]]:
    """Load the persisted video information used to avoid duplicate processing."""

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_video_store(store: MutableMapping[str, Dict[str, object]], path: str = VIDEO_STORE_PATH) -> None:
    """Persist the updated video information to disk."""

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=4, ensure_ascii=False)


def _is_video_processed(video_id: str, store: MutableMapping[str, Dict[str, object]]) -> bool:
    return video_id in store


def _update_video_entry(
    store: MutableMapping[str, Dict[str, object]],
    video: Dict[str, str],
    transcript: str,
    stocks: List[Dict[str, object]],
) -> None:
    """Merge transcript and Gemini analysis into the shared video store."""

    entry = store.setdefault(video["id"], {})
    entry.setdefault("summary", {})
    entry.setdefault("transcript", transcript)
    if not entry.get("transcript"):
        entry["transcript"] = transcript
    entry["stocks"] = stocks
    entry["metadata"] = video
    entry["analysed_at"] = datetime.utcnow().isoformat() + "Z"


def process_channel(
    channel_id: str,
    api_key: str,
    *,
    limit: int = 5,
    store: Optional[MutableMapping[str, Dict[str, object]]] = None,
) -> List[Tuple[Dict[str, str], List[Dict[str, object]]]]:
    """Check a single channel for new videos and analyse them."""

    if store is None:
        store = load_video_store()

    latest_videos = fetch_latest_videos(channel_id, limit=limit)
    new_videos = [video for video in latest_videos if not _is_video_processed(video["id"], store)]

    results: List[Tuple[Dict[str, str], List[Dict[str, object]]]] = []

    channel_name = next((ch.get("name") for ch in CHANNELS if ch.get("id") == channel_id), channel_id)

    if not new_videos:
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} – No new videos for {channel_name}.")
        return results

    print(
        f"{datetime.now():%Y-%m-%d %H:%M:%S} – Found {len(new_videos)} new video(s) for {channel_name}."
    )

    for video in reversed(new_videos):  # Oldest first for chronological output
        print(f" → Processing: {video['title']} ({video['url']})")
        transcript = _fetch_transcript(video["id"])
        if not transcript:
            print("   ! Transcript unavailable – skipping Gemini analysis.")
            continue

        stocks = extract_stock_sentiments(transcript, api_key=api_key)
        _update_video_entry(store, video, transcript, stocks)

        results.append((video, stocks))

        if stocks:
            print("   ✓ Stocks mentioned:")
            print(json.dumps(stocks, indent=2, ensure_ascii=False))
        else:
            print("   – No stocks discussed or model returned an empty list.")

    save_video_store(store)
    return results


def check_for_new_videos(
    api_key: str,
    *,
    channels: Optional[Sequence[str]] = None,
    limit: int = 5,
    store: Optional[MutableMapping[str, Dict[str, object]]] = None,
) -> Dict[str, List[Tuple[Dict[str, str], List[Dict[str, object]]]]]:
    """Check all configured channels for new videos and run Gemini analysis."""

    if channels is None:
        channels = [channel["id"] for channel in CHANNELS]

    if not channels:
        print("No channels configured. Add channel IDs to the CHANNELS list.")
        return {}

    if store is None:
        store = load_video_store()

    summary: Dict[str, List[Tuple[Dict[str, str], List[Dict[str, object]]]]] = {}
    for channel_id in channels:
        summary[channel_id] = process_channel(channel_id, api_key=api_key, limit=limit, store=store)

    save_video_store(store)
    return summary

