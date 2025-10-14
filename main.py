import streamlit as st
from utils import load_json_file, get_video_id, transcipt_path, key_exists, save_to_json, get_yt_transcript, my_generator, save_stream_to_json, summarize_transcript_stream
from dotenv import load_dotenv
import os
from google import genai

load_dotenv()
summary_path = os.getenv("SUMMARY_JSON_PATH", "summary.json")

API_KEY = os.getenv("API_KEY")
transcript_dict = load_json_file(transcipt_path)
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
            transcript_dict[video_id] = transcript
        else:
            st.error(result["error"])
            st.stop()

        save_to_json(transcript_dict, transcipt_path)

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
