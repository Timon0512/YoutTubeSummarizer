from urllib.parse import urlparse, parse_qs
import json
import time
import os
import re
from typing import Any, Dict, List
from youtube_transcript_api import YouTubeTranscriptApi, _errors
from google import genai
import shutil, datetime




def key_exists(keys: list, dictionary: dict):
    d = dictionary
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return False
    return True

def save_stream_to_json(stream, path, language, video_id, dictionary):
    collected = []
    # Iteriere über den Stream
    for chunk in stream:
        collected.append(chunk)
        yield chunk  # gleichzeitig weitergeben an Streamlit

    # Am Ende zusammenfügen und speichern
    result = "".join(collected)

    if video_id not in dictionary:
        dictionary[video_id] = {}

    dictionary[video_id][language] = result

    with open(path, "w", encoding="utf-8") as f:
        json.dump(dictionary, f, indent=4, ensure_ascii=False)

def my_generator(text: str):
    str_list = text.split(" ")
    for word in str_list:
        yield word + " "
        time.sleep(0.02)

def load_json_file(path):
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
    except (
        _errors.TranscriptsDisabled,
        _errors.NoTranscriptFound,
        _errors.NotTranslatable,
        _errors.VideoUnavailable,
        _errors.CouldNotRetrieveTranscript,
        _errors.YouTubeTranscriptApiException,
    ) as e:
        return {
            "success": False,
            "data": None,
            "error": e
        }
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
    return {
            "success": True,
            "data": full_transcript,
            "error": None
        }

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


def get_llm_stock_rating(transcript: str, api_key: str, language: str = "DE"):

    prompt = f"""
        You are a senior equity research analyst specializing in interpreting earnings call transcripts and investor communications. 
        Your goal is to evaluate the company's overall investment attractiveness based on qualitative statements in the text. 
        Analyze the transcript carefully and assess the following five dimensions: 
        
        1. **Growth Outlook (-1 to +1)** — How optimistic or pessimistic is management about future revenue or market growth? 
        2. **Profitability (-1 to +1)** — How confident is management regarding margins, cost efficiency, and profitability trends? 
        3. **Market Conditions (-1 to +1)** — How positive or negative is management’s view of market demand, competition, and external conditions? 
        4. **Guidance (0 to 1)** — How clear, specific, and credible is management’s guidance or forward-looking statements? 
        5. **Sentiment (-1 to +1)** — The overall emotional tone/sentiment of management (positive, neutral, or negative). 
            
        Return a json table with following columns: [Stock Name, Stock Ticker, Stock ISIN, Growth Outlook, Profitability, Market Conditions, Guidance, Sentiment] 
        If no stocks are discussed, please return an empty json dict. 
        Please do not response with any kind of unstructured text. 
        ---
        {transcript}
        ---
        """

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model='gemma-3n-e2b-it',
        contents=prompt,
    )

    return response.text


def save_to_json(video_dict, json_path):
    """Speichert das video_dict sicher als JSON und erstellt Backup bei Fehler."""
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(video_dict, f, indent=4, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"❌ Fehler beim Speichern von {json_path}: {e}")
        # Backup erstellen
        backup = f"{json_path}.{datetime.datetime.now():%Y%m%d_%H%M%S}.bak"
        shutil.copy(json_path, backup)
        raise e


# def get_transcript(json_path, id):
#     video_dict = load_video_dict(json_path)
#     return video_dict.get(id, {})["transcript"]

def clean_and_parse_json(llm_output: str, save_path: str = None):
    """
    Bereinigt und parsed fehlerhafte JSON-Ausgaben von LLMs.

    Args:
        llm_output (str): Der rohe Output vom LLM (z. B. mit Zusatztext)
        save_path (str, optional): Pfad, unter dem das JSON gespeichert werden soll

    Returns:
        data (dict | list): Geparstes JSON-Objekt
    """
    # 1️⃣ Versuch: Direktes Laden (vielleicht ist es ja schon gültig)
    try:
        data = json.loads(llm_output)
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        return data
    except json.JSONDecodeError:
        pass  # Weiter unten wird bereinigt

    # 2️⃣ Nur den JSON-ähnlichen Teil extrahieren (alles zwischen [ ... ] oder { ... })
    match = re.search(r"(\[.*\]|\{.*\})", llm_output, re.DOTALL)
    if not match:
        raise ValueError("❌ Kein JSON-ähnlicher Block im Text gefunden.")

    json_like = match.group(1)

    # 3️⃣ Häufige Fehler automatisch korrigieren
    json_like = (
        json_like
        .replace("'", '"')  # einfache Quotes in doppelte umwandeln
        .replace("True", "true")
        .replace("False", "false")
        .replace("None", "null")
    )

    # 4️⃣ Überzählige Kommas am Ende von Listen/Objekten entfernen
    json_like = re.sub(r",(\s*[}\]])", r"\1", json_like)

    # 5️⃣ Zweiter Versuch: Laden
    try:
        data = json.loads(json_like)
    except json.JSONDecodeError as e:
        print("⚠️ JSON Parsing Fehler:", e)
        print("Versuch einer Reparatur...")
        # Falls immer noch fehlerhaft → etwas aggressiver reparieren
        json_like = re.sub(r"[\x00-\x1F\x7F]", "", json_like)  # unsichtbare Zeichen
        data = json.loads(json_like)

    # 6️⃣ Optional speichern
    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    return data


#
# text = get_transcript(json_path,"f5_YEimKDXI")
# table = return_stock_table(transcript=text, api_key=API_KEY)
# print(table)
# cleaned_table = clean_and_parse_json(table)
# print(cleaned_table)

