"""Utilities to monitor YouTube channels and analyse new videos with Gemini.

This module keeps track of multiple YouTube channels by storing a small JSON state
file locally. Whenever new uploads are detected it fetches the transcript, sends it
to Gemini via the helper utilities in :mod:`utils` and prints the extracted stock
sentiment information.

Typical usage::

    # Add a channel to the watch list
    python new_video_check.py add UCyCBf6asf89aQJaSXuAuTsg --name "My Channel"

    # Check for new videos on all configured channels
    GEMINI_API_KEY=... python new_video_check.py check

The state file ``channel_state.json`` keeps track of processed videos so that each
upload is only analysed once.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET

import requests
from youtube_transcript_api import YouTubeTranscriptApi, _errors

from utils import extract_stock_sentiments


STATE_FILE = "channel_state.json"


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


def load_state() -> Dict[str, Dict[str, Dict[str, object]]]:
    """Load the persisted channel state from disk."""

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = {}

    data.setdefault("channels", {})
    return data  # type: ignore[return-value]


def save_state(state: Dict[str, Dict[str, Dict[str, object]]]) -> None:
    """Persist the channel state to disk."""

    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)


def add_channel(channel_id: str, name: Optional[str] = None, limit: int = 5) -> None:
    """Add a new YouTube channel to the watch list.

    The latest videos are stored as the baseline so that only future uploads are
    analysed.
    """

    state = load_state()
    channels = state["channels"]

    if channel_id in channels:
        print(f"Channel {channel_id} is already tracked.")
        return

    videos = fetch_latest_videos(channel_id, limit=limit)

    channels[channel_id] = {
        "name": name or channel_id,
        "known_videos": [video["id"] for video in videos],
        "analyses": {},
    }

    save_state(state)
    print(f"Added channel {channel_id} ({channels[channel_id]['name']}).")


def list_channels() -> None:
    """Print a table with all configured channels."""

    state = load_state()
    channels = state.get("channels", {})

    if not channels:
        print("No channels configured yet. Use the 'add' command to add one.")
        return

    print("Tracked channels:")
    for idx, (channel_id, info) in enumerate(channels.items(), start=1):
        name = info.get("name", channel_id)
        known = len(info.get("known_videos", []))
        print(f" {idx:>2}. {name} ({channel_id}) – cached videos: {known}")


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


def _update_known_videos(channel_state: Dict[str, object], latest_videos: Iterable[Dict[str, str]]) -> None:
    """Maintain a rolling window of known video IDs for a channel."""

    latest_ids = [video["id"] for video in latest_videos]
    existing: List[str] = list(channel_state.get("known_videos", []))  # type: ignore[arg-type]
    combined = latest_ids + [vid for vid in existing if vid not in latest_ids]
    channel_state["known_videos"] = combined[:50]


def process_channel(
    channel_id: str,
    api_key: str,
    limit: int = 5,
    state: Optional[Dict[str, Dict[str, Dict[str, object]]]] = None,
) -> List[Tuple[Dict[str, str], List[Dict[str, object]]]]:
    """Check a single channel for new videos and analyse them."""

    if not state:
        state = load_state()

    channels = state.setdefault("channels", {})
    channel_state = channels.get(channel_id)
    if not channel_state:
        raise ValueError(f"Channel {channel_id} is not configured. Use the 'add' command first.")

    latest_videos = fetch_latest_videos(channel_id, limit=limit)
    known_ids = set(channel_state.get("known_videos", []))
    new_videos = [video for video in latest_videos if video["id"] not in known_ids]

    results: List[Tuple[Dict[str, str], List[Dict[str, object]]]] = []

    if not new_videos:
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} – No new videos for {channel_state.get('name', channel_id)}.")
    else:
        print(
            f"{datetime.now():%Y-%m-%d %H:%M:%S} – Found {len(new_videos)} new video(s) for "
            f"{channel_state.get('name', channel_id)}."
        )

    channel_state.setdefault("analyses", {})
    analyses: Dict[str, object] = channel_state["analyses"]  # type: ignore[assignment]

    for video in reversed(new_videos):  # Oldest first for chronological output
        print(f" → Processing: {video['title']} ({video['url']})")
        transcript = _fetch_transcript(video["id"])
        if not transcript:
            print("   ! Transcript unavailable – skipping Gemini analysis.")
            continue

        stocks = extract_stock_sentiments(transcript, api_key=api_key)
        analyses[video["id"]] = {
            "video": video,
            "stocks": stocks,
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

        results.append((video, stocks))

        if stocks:
            print("   ✓ Stocks mentioned:")
            print(json.dumps(stocks, indent=2, ensure_ascii=False))
        else:
            print("   – No stocks discussed or model returned an empty list.")

    _update_known_videos(channel_state, latest_videos)
    save_state(state)
    return results


def check_for_new_videos(
    api_key: str,
    channel_ids: Optional[List[str]] = None,
    limit: int = 5,
) -> Dict[str, List[Tuple[Dict[str, str], List[Dict[str, object]]]]]:
    """Check all or selected channels for new videos and run Gemini analysis."""

    state = load_state()
    channels = state.get("channels", {})
    if not channels:
        print("No channels configured yet. Use the 'add' command to add one.")
        return {}

    if channel_ids is None:
        channel_ids = list(channels.keys())

    summary: Dict[str, List[Tuple[Dict[str, str], List[Dict[str, object]]]]] = {}
    for channel_id in channel_ids:
        if channel_id not in channels:
            print(f"Channel {channel_id} is not configured – skipping.")
            continue
        summary[channel_id] = process_channel(channel_id, api_key=api_key, limit=limit, state=state)

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add a new channel to the watch list")
    add_parser.add_argument("channel_id", help="YouTube channel ID to monitor")
    add_parser.add_argument("--name", help="Optional human readable label", default=None)
    add_parser.add_argument("--limit", type=int, default=10, help="Initial number of videos to cache")

    subparsers.add_parser("list", help="List configured channels")

    check_parser = subparsers.add_parser("check", help="Check tracked channels for new videos")
    check_parser.add_argument("--channel", action="append", dest="channels", help="Limit to specific channel IDs")
    check_parser.add_argument("--limit", type=int, default=5, help="Number of latest videos to inspect per channel")
    check_parser.add_argument("--api-key", dest="api_key", help="Gemini API key. Defaults to GEMINI_API_KEY env var")

    parser.set_defaults(command="check")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    command = args.command

    if command == "add":
        add_channel(args.channel_id, name=args.name, limit=args.limit)
        return

    if command == "list":
        list_channels()
        return

    # Default command: check
    api_key = getattr(args, "api_key", None) or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Gemini API key missing. Provide via --api-key or GEMINI_API_KEY env var.")

    check_for_new_videos(api_key=api_key, channel_ids=getattr(args, "channels", None), limit=args.limit)


if __name__ == "__main__":
    main()

