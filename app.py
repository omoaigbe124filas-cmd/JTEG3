import streamlit as st
from google import genai
import speech_recognition as sr
from gtts import gTTS
import io

st.set_page_config(page_title="VINCI VOICE - JTEG", page_icon="🎙️")
st.title("VINCI AI - VOICE MODE 🎙️")
st.caption("Josiah Technologies and Engineering Group | JTEG = Josiah Technologies and Engineering Group")

MY_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not MY_KEY:
    st.error("No API Key in Secrets")
    st.stop()

client = genai.Client(api_key=MY_KEY)

if "messages" not in st.session_state:
    st.session_state.messages = []

if st.button("Clear chat"):
    st.session_state.messages = []
    st.rerun()

# Show history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        if msg.get("audio"):
            st.audio(msg["audio"])

# --- VOICE INPUT ---
st.markdown("### 🎤 Talk to VINCI")
audio = st.audio_input("Tap mic and speak")

prompt = None

if audio:
    # Convert voice to text
    with st.spinner("VINCI is listening..."):
        try:
            r = sr.Recognizer()
            # Save uploaded audio to bytes for recognizer
            audio_bytes = audio.read()
            with open("temp_voice.wav", "wb") as f:
                f.write(audio_bytes)
            with sr.AudioFile("temp_voice.wav") as source:
                audio_data = r.record(source)
                prompt = r.recognize_google(audio_data)
                st.success(f"You said: {prompt}")
        except Exception as e:
            st.error(f"Could not hear you clearly, try again. Error: {e}")

# --- TEXT INPUT ALSO STILL THERE ---
text_prompt = st.chat_input("Or type here...")
if text_prompt:
    prompt = text_prompt

# --- VINCI ANSWERS ---
if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("VINCI is thinking..."):
            try:
                models_to_try = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]
                response = None
                last_error = ""
                for m in models_to_try:
                    try:
                        response = client.models.generate_content(
                            model=m,
                            contents=f"You are VINCI AI for JTEG = Josiah Technologies and Engineering Group. User is Josiah, aspiring Electrical Engineer in Birnin-Kebbi, CEO of JTEG. Be like Jarvis: smart, short, confident, friendly. Keep answer short so voice is fast. User says: {prompt}"
                        )
                        break
                    except Exception as e:
                        last_error = str(e)
                        continue

                if response is None:
                    st.error(f"Google busy. Wait 1 min. {last_error[:200]}")
                else:
                    answer = response.text
                    st.markdown(answer)

                    # VINCI SPEAKS BACK
                    try:
                        tts = gTTS(text=answer[:500], lang='en')
                        mp3_fp = io.BytesIO()
                        tts.write_to_fp(mp3_fp)
                        mp3_fp.seek(0)
                        st.audio(mp3_fp, format="audio/mp3")
                        st.session_state.messages.append({"role": "assistant", "text": answer, "audio": mp3_fp.getvalue()})
                    except Exception as e:
                        st.session_state.messages.append({"role": "assistant", "text": answer})
                        st.warning(f"Voice reply failed, but text works: {e}")
            except Exception as e:
                st.error(f"VINCI ERROR: {e}")
