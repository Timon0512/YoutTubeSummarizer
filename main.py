import streamlit as st
from utils import *
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
json_path = "video_dict.json"

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
                                    default="English",
                                    )

else:
    st.stop()

if st.button("Summarize"):
    tab_summary, tab_transcript = st.tabs(["Ai powered Summary", "Transcript"])

    if key_exists([video_id]):
        trans = video_dict.get(video_id)["transcript"]
        # st.write("get trans from dict")
    else:
        # st.write("get trans NOT from dict")
        result = get_yt_transcript(video_id)
        if result["success"]:
            trans = result["data"]
            video_dict[video_id] = {"transcript": trans,
                                    "summary": {}
                                    }
        else:
            st.error(result["error"])
            st.stop()

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(video_dict, f, indent=4, ensure_ascii=False)


    with tab_summary:

        if key_exists([video_id, "summary", output_language]):
            # st.write("key exists")
            summary = video_dict.get(video_id)["summary"].get(output_language)
            st.write_stream(my_generator(summary))


        else:
            # st.write("key does NOT exists")

            try:
                st.write_stream(
                    save_stream_to_json(
                        summarize_transcript_stream(trans, api_key=API_KEY, language=output_language),
                        path=json_path,
                        language=output_language,
                        video_id=video_id,
                    )
                )


            except genai.errors.ClientError as e:
                    st.error(e)

    with tab_transcript:
        st.write(trans)
