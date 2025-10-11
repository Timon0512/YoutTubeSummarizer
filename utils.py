from urllib.parse import urlparse, parse_qs
import json
import time
import os
import re
from typing import Any, Dict, List
from youtube_transcript_api import YouTubeTranscriptApi, _errors
import streamlit as st
from google import genai


# Default location for storing cached video data. Allows overriding via environment
# variable so that the module can also be reused from command line utilities.
json_path = os.getenv("VIDEO_JSON_PATH", "video_dict.json")

def get_language(country_iso):
    my_dict = {
        "DE": "German",
        "EN": "English",
        "ES": "Spanish",
        "IT": "Italian",
        "CN": "Chinese",
    }
    return my_dict.get(country_iso)

def save_stream_to_json(stream, path, language, video_id):
    collected = []
    # Iteriere über den Stream
    for chunk in stream:
        collected.append(chunk)
        yield chunk  # gleichzeitig weitergeben an Streamlit

    # Am Ende zusammenfügen und speichern
    result = "".join(collected)
    global video_dict

    if language not in video_dict[video_id]["summary"]:
        video_dict[video_id]["summary"][language] = result

    with open(path, "w", encoding="utf-8") as f:
        json.dump(video_dict, f, indent=4, ensure_ascii=False)

def my_generator(text: str):
    str_list = text.split(" ")
    for word in str_list:
        yield word + " "
        time.sleep(0.02)

def load_video_dict(path):
    if os.path.exists(path):
        # Datei laden
        with open(path, "r", encoding="utf-8") as f:
            video_dict = json.load(f)
    else:
        # Neues Dict anlegen
        video_dict = {}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(video_dict, f, indent=4)
    return video_dict


video_dict = load_video_dict(json_path)


def key_exists(keys: list):
    global video_dict
    d = video_dict
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return False
    return True


def get_video_id(url: str):
    """Extract YouTube video ID from multiple URL formats."""
    parsed = urlparse(url)

    # 1) youtu.be/<id>
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        return parsed.path[1:]

    # 2) youtube.com/watch?v=<id>
    if parsed.path == "/watch":
        return parse_qs(parsed.query).get("v", [None])[0]

    # 3) youtube.com/embed/<id>, youtube.com/v/<id>, youtube.com/live/<id>
    if parsed.path.startswith(("/embed/", "/v/", "/live/","/shorts/")):
        return parsed.path.split("/")[2]

    return None

def get_yt_transcript(video_id: str,
                      start_sec: int=0,
                      end_sec: float=float("inf")):
    str_list = []
    ytt_api = YouTubeTranscriptApi()
    try:
        transcript_list = ytt_api.list(video_id)
    except _errors.TranscriptsDisabled:
        st.info("Transcript Disabled for this video. "
                "Use Whisper....")
        st.stop()
    except _errors.IpBlocked:
        st.info("Your IP has been blocked from YoutTube. "
                "Not able to download the transcript.")
        st.stop()
    language_list = []
    for transcript in transcript_list:
        language_list.append(transcript.language_code)

    use_language = language_list[0]
    transcript = ytt_api.fetch(video_id=video_id, languages=[use_language])
    for snippet in transcript:
        # print(snippet)
        if start_sec <= float(snippet.start) <= end_sec:
            # print(snippet.text)
            str_list.append(snippet.text)

    full_transcript = " ".join(str_list)
    return full_transcript

def summarize_transcript_stream(transcript: str, api_key: str, language: str = "DE"):

    prompt = f"""
        You are an expert at summarizing YouTube video transcripts.
        Your goal is to provide a clear and concise summary that captures the essence of the video.
        The summary must be written in {language}.
        Please format your response in Markdown.

        The summary should have the following structure:
        1.  A short, catchy title for the summary. Use a heading level 2 (##).
        2.  A one-paragraph overview of the video's main topic and conclusion.
        3.  A bulleted list of the 3-5 most important key takeaways or points discussed. Use a heading level 3 (###) for "Key Takeaways".

        Here is the transcript:
        ---
        {transcript}
        ---
        """

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content_stream(
        model='gemma-3n-e2b-it',
        contents=prompt,
    )
    for chunk in response:
        if chunk.text is not None:
            yield chunk.text

    return ""


def build_stock_sentiment_prompt(transcript: str) -> str:
    """Create a prompt for Gemini to extract discussed stocks with sentiments."""

    return f"""
You are a financial analyst who analyses transcripts of finance-related YouTube videos.
Read the following transcript carefully and identify every individual stock, ETF or
publicly traded company that is discussed.

For each mentioned security return a JSON array where every element has the following keys:
  - "ticker": The commonly used stock ticker if explicitly mentioned, otherwise infer it from context.
  - "company": The full company or fund name.
  - "sentiment": One of "buy", "sell" or "neutral" representing the speaker's stance.
  - "evidence": A short quote or reasoning from the transcript that justifies the sentiment.

Important rules:
  * Only output valid JSON – do not include explanations or commentary.
  * If no securities are discussed, return an empty JSON array ("[]").

Transcript:
---
{transcript}
---
"""


def _extract_json_payload(raw_text: str) -> Any:
    """Best-effort conversion of a model response into JSON."""

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        end_idx = cleaned.rfind("```")
        if end_idx != -1:
            cleaned = cleaned[:end_idx]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: try to locate the first JSON-like structure.
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


def extract_stock_sentiments(transcript: str, api_key: str, model: str = "gemma-3n-e2b-it") -> List[Dict[str, Any]]:
    """Return mentioned stocks with sentiment analysis using Gemini."""

    prompt = build_stock_sentiment_prompt(transcript)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )

    if not response or not getattr(response, "text", None):
        return []

    try:
        payload = _extract_json_payload(response.text)
    except json.JSONDecodeError:
        return []

    if isinstance(payload, list):
        return payload

    return [payload]
