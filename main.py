import streamlit as st
from utils import load_json_file, get_video_id, key_exists, save_to_json, get_yt_transcript, my_generator, save_stream_to_json, summarize_transcript_stream, get_video_data
from dotenv import load_dotenv
import os
from google import genai
from datetime import datetime
from googleapiclient.discovery import build

load_dotenv()
summary_path = os.path.join(os.path.dirname(__file__), "summary.json")
transcript_path = os.path.join(os.path.dirname(__file__), "transcripts.json")

API_KEY = os.getenv("API_KEY")
GOOGLE_API = os.getenv("GOOGLE_API")
transcript_dict = load_json_file(transcript_path)
summary_dict = load_json_file(summary_path)

st.title("Youtube Video Summarizer :clapper:")
st.markdown("Paste a YouTube link to get a quick AI-powered summary.:notebook:")
video_url = st.text_input(" ", value="Paste your YouTube URL here...")

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
                                    default="German",
                                    )

else:
    st.stop()
with st.spinner("Loading Transcript"):
    if key_exists([video_id], dictionary=transcript_dict):
        transcript = transcript_dict.get(video_id)
    else:
        result = get_yt_transcript(video_id)
        if result["success"]:
            transcript = result["data"]
            youtube = build("youtube", "v3", developerKey=GOOGLE_API)
            video = get_video_data(youtube, video_id)
            video_entry = {"name": "Website",
                           **video,
                           "processed_on": datetime.now(),
                           "transcript": transcript}
            transcript_dict[video_id] = video_entry
        else:
            st.error(result["error"])
            st.stop()

        save_to_json(transcript_dict, transcript_path)

if st.button("Summarize"):
    tab_summary, tab_transcript = st.tabs(["Ai powered Summary", "Transcript"])

    with tab_summary:

        if key_exists([video_id, output_language], summary_dict):
            summary = summary_dict[video_id][output_language]
            st.write_stream(my_generator(summary))
        else:

            try:
                st.write_stream(
                    save_stream_to_json(
                        summarize_transcript_stream(transcript, api_key=API_KEY, language=output_language),
                        path=summary_path,
                        language=output_language,
                        video_id=video_id,
                        dictionary=summary_dict
                    )
                )

            except genai.errors.ClientError as e:
                    st.error(e)

    with tab_transcript:
        st.write(transcript)
