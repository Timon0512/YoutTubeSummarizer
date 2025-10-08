import time
import os
from youtube_transcript_api import YouTubeTranscriptApi, _errors
from google import genai
import streamlit as st
import re
import json
from urllib.parse import urlparse, parse_qs

API_KEY = st.secrets["API_KEY"]
json_path = "video_dict.json"

DEFAULT_SUMMARY_PROMPT = """
You are an expert at summarizing YouTube video transcripts.
Your goal is to provide a clear and concise summary that captures the essence of the video.
The summary must be written in {language}.
Please format your response in Markdown.

The summary should have the following structure:
1. A short, catchy title for the summary. Use a heading level 2 (##).
2. A one-paragraph overview of the video's main topic and conclusion.
3. A bulleted list of the 3-5 most important key takeaways or points discussed. Use a heading level 3 (###) for "Key Takeaways".

Here is the transcript:
---
{transcript}
---
""".strip()

DEFAULT_STOCK_PROMPT = """
You are a financial analyst. Identify all stocks or companies that are explicitly discussed in the transcript below.
For each mentioned stock, determine whether the overall sentiment is Positive, Negative, or Neutral.
Respond in {language} using Markdown with a table that has the columns: Unternehmen/Aktie, Sentiment, Begründung.
If no stocks are discussed, explicitly state that no stocks were mentioned.

Transcript:
---
{transcript}
---
""".strip()
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

# def get_video_id(url: str):
#     """Extracts the YouTube video ID from a URL."""
#     regex = r"^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|&v=)([^#&?]*).*"
#     match = re.match(regex, url)
#     return match.group(2) if match and len(match.group(2)) == 11 else None

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

def stream_model_response(prompt: str, api_key: str):
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content_stream(
        model='gemma-3n-e2b-it',
        contents=prompt,
    )
    for chunk in response:
        if chunk.text is not None:
            yield chunk.text

    return ""


def summarize_transcript_stream(transcript: str, api_key: str, language: str, prompt_template: str):
    prompt = prompt_template.format(language=language, transcript=transcript)
    return stream_model_response(prompt, api_key)


def stock_sentiment_stream(transcript: str, api_key: str, language: str, prompt_template: str):
    prompt = prompt_template.format(language=language, transcript=transcript)
    return stream_model_response(prompt, api_key)

def get_language(country_iso):
    my_dict = {
        "DE": "German",
        "EN": "English",
        "ES": "Spanish",
        "IT": "Italian",
        "CN": "Chinese",
    }
    return my_dict.get(country_iso)

def save_stream_to_json(stream, path, language, video_id, *, store=True, target_key="summary"):
    collected = []
    # Iteriere über den Stream
    for chunk in stream:
        collected.append(chunk)
        yield chunk  # gleichzeitig weitergeben an Streamlit

    # Am Ende zusammenfügen und speichern
    result = "".join(collected)
    if not store:
        return

    global video_dict
    video_entry = video_dict.setdefault(video_id, {})
    target_dict = video_entry.setdefault(target_key, {})
    target_dict[language] = result

    with open(path, "w", encoding="utf-8") as f:
        json.dump(video_dict, f, indent=4, ensure_ascii=False)

def my_generator(text: str):
    str_list = text.split(" ")
    for word in str_list:
        yield word + " "
        time.sleep(0.02)


st.title("Youtube Video Summarizer :clapper:")
st.markdown("Paste a YouTube link to get a quick AI-powered summary.:notebook:")
video_url = st.text_input(" ", value="Paste your YouTube URL here...")

summary_prompt_template = DEFAULT_SUMMARY_PROMPT
stock_prompt_template = DEFAULT_STOCK_PROMPT

if video_url != "Paste your YouTube URL here...":
    video_id = get_video_id(video_url)
    if video_id is None:
        st.error("Please insert a valid Youtube url!\n"
                 "YouTube shorts are not allowed.")
        st.stop()

    else:

        st.video(video_url)
        output_language = st.pills("Select your desired output language",
                                    options=["English", "German", "Spanish", "French", "Portuguese", "Italian",
                                            "Chinese", "Japanese", "Arabic"],
                                    default="English",
                                    )

        with st.expander("LLM Prompt Einstellungen", expanded=False):
            st.caption("Nutze die Platzhalter {language} und {transcript}, um Sprache und Inhalt zu steuern.")
            summary_prompt_template = st.text_area(
                "Prompt für die Zusammenfassung",
                value=DEFAULT_SUMMARY_PROMPT,
                height=260,
                key="summary_prompt_input",
            )
            stock_prompt_template = st.text_area(
                "Prompt für Aktien-Sentiment",
                value=DEFAULT_STOCK_PROMPT,
                height=220,
                key="stock_prompt_input",
            )

else:
    st.stop()

if st.button("Summarize"):
    tab_summary, tab_transcript, tab_stocks = st.tabs(["Ai powered Summary", "Transcript", "Besprochene Aktien"])

    if key_exists([video_id]):
        trans = video_dict.get(video_id)["transcript"]
        # st.write("get trans from dict")
    else:
        # st.write("get trans NOT from dict")
        trans = get_yt_transcript(video_id)
        video_dict[video_id] = {"transcript": trans,
                                "summary": {},
                                "stock_sentiment": {},
                                }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(video_dict, f, indent=4, ensure_ascii=False)


    with tab_summary:

        store_summary = summary_prompt_template.strip() == DEFAULT_SUMMARY_PROMPT
        if store_summary and key_exists([video_id, "summary", output_language]):
            summary = video_dict.get(video_id)["summary"].get(output_language)
            st.write_stream(my_generator(summary))


        else:
            # st.write("key does NOT exists")

            try:
                st.write_stream(
                    save_stream_to_json(
                        summarize_transcript_stream(
                            trans,
                            api_key=API_KEY,
                            language=output_language,
                            prompt_template=summary_prompt_template,
                        ),
                        path=json_path,
                        language=output_language,
                        video_id=video_id,
                        store=store_summary,
                        target_key="summary",
                    )
                )


            except KeyError as e:
                missing_key = e.args[0]
                st.error(f"Der Prompt muss den Platzhalter {{{missing_key}}} enthalten.")
                st.stop()
            except genai.errors.ClientError as e:
                st.error(e)

    with tab_transcript:
        st.write(trans)

    with tab_stocks:
        store_stock = stock_prompt_template.strip() == DEFAULT_STOCK_PROMPT
        if store_stock and key_exists([video_id, "stock_sentiment", output_language]):
            stock_summary = video_dict.get(video_id)["stock_sentiment"].get(output_language)
            st.write_stream(my_generator(stock_summary))

        else:
            try:
                st.write_stream(
                    save_stream_to_json(
                        stock_sentiment_stream(
                            trans,
                            api_key=API_KEY,
                            language=output_language,
                            prompt_template=stock_prompt_template,
                        ),
                        path=json_path,
                        language=output_language,
                        video_id=video_id,
                        store=store_stock,
                        target_key="stock_sentiment",
                    )
                )
            except KeyError as e:
                missing_key = e.args[0]
                st.error(f"Der Prompt muss den Platzhalter {{{missing_key}}} enthalten.")
                st.stop()
            except genai.errors.ClientError as e:
                st.error(e)
