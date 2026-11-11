import streamlit as st
from google import genai
import speech_recognition as sr
from gtts import gTTS
import io
from datetime import datetime, date, time

st.set_page_config(page_title="VINCI - JTEG", page_icon="🤖", layout="wide")

# ===== BEAUTIFUL BACKGROUND / THEME =====
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
    background-attachment: fixed;
}
h1, h2, h3 { color: white !important; }
.stCaption, p, label { color: #e0e0e0 !important; }
div[data-testid="stChatMessage"] {
    background: rgba(255,255,255,0.08);
    border-radius: 15px;
    padding: 10px;
    border: 1px solid rgba(255,255,255,0.15);
    backdrop-filter: blur(10px);
}
.stButton > button {
    background: linear-gradient(90deg, #00c6ff, #0072ff);
    color: white; border: none; border-radius: 20px;
    font-weight: bold;
}
.stTextInput input, .stTextArea textarea, .stSelectbox div {
    background: rgba(255,255,255,0.9) !important;
    border-radius: 12px !important;
}
</style>
""", unsafe_allow_html=True)

st.title("🤖 VINCI AI - JTEG")
st.caption("Josiah Technologies and Engineering Group | JTEG = Josiah Technologies and Engineering Group")
st.caption("CEO: Josiah | Birnin-Kebbi | Model: Gemini 3.5 Flash-Lite ONLY")

MY_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not MY_KEY:
    st.error("No API Key in Secrets")
    st.stop()

client = genai.Client(api_key=MY_KEY)

# ===== MEMORY =====
if "messages" not in st.session_state:
    st.session_state.messages = []
if "projects" not in st.session_state:
    st.session_state.projects = []
if "reminders" not in st.session_state:
    st.session_state.reminders = []

# ===== SIDEBAR - PROJECTS + REMINDERS =====
with st.sidebar:
    st.header("📁 My Projects - JTEG")
    st.write("Store your ideas here, VINCI will remember them.")

    proj_title = st.text_input("Project Name", placeholder="e.g. Smart Solar Charger")
    proj_desc = st.text_area("Project Details", placeholder="What is it? Materials? Progress?")
    proj_status = st.selectbox("Status", ["Idea 💡", "In Progress 🔨", "Done ✅", "Paused ⏸️"])
    if st.button("Save Project"):
        if proj_title:
            st.session_state.projects.append({"title": proj_title, "desc": proj_desc, "status": proj_status, "date": str(date.today())})
            st.success(f"Saved: {proj_title}")
            st.rerun()
        else:
            st.warning("Type project name first")

    st.divider()
    for i, p in enumerate(st.session_state.projects):
        with st.expander(f"{p['status']} - {p['title']}"):
            st.write(p['desc'])
            st.caption(f"Saved: {p['date']}")
            if st.button(f"Delete {p['title']}", key=f"del_proj_{i}"):
                st.session_state.projects.pop(i)
                st.rerun()

    st.divider()
    st.header("⏰ Scheduled Reminders")
    rem_text = st.text_input("Reminder", placeholder="e.g. Charge battery, Study circuits")
    rem_date = st.date_input("Date", value=date.today())
    rem_time = st.time_input("Time", value=time(8, 0))
    if st.button("Set Reminder"):
        if rem_text:
            st.session_state.reminders.append({"text": rem_text, "date": str(rem_date), "time": str(rem_time)})
            st.success("Reminder set!")
            st.rerun()

    for i, r in enumerate(st.session_state.reminders):
        st.info(f"⏰ {r['date']} at {r['time']} - {r['text']}")
        if st.button(f"Done", key=f"del_rem_{i}"):
            st.session_state.reminders.pop(i)
            st.rerun()

    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.rerun()

# ===== SHOW REMINDERS DUE TODAY ON TOP =====
today_str = str(date.today())
todays = [r for r in st.session_state.reminders if r['date'] == today_str]
if todays:
    st.warning(f"🔔 You have {len(todays)} reminder(s) today!")
    for r in todays:
        st.write(f"⏰ {r['time']} - {r['text']}")

# ===== CHAT HISTORY =====
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        if msg.get("audio"):
            st.audio(msg["audio"])

# ===== VOICE INPUT =====
st.markdown("### 🎤 Talk to VINCI")
audio = st.audio_input("Tap mic and speak")
prompt = None

if audio:
    with st.spinner("VINCI is listening..."):
        try:
            r = sr.Recognizer()
            audio_bytes = audio.read()
            with open("temp_voice.wav", "wb") as f:
                f.write(audio_bytes)
            with sr.AudioFile("temp_voice.wav") as source:
                audio_data = r.record(source)
                prompt = r.recognize_google(audio_data)
                st.success(f"You said: {prompt}")
        except Exception as e:
            st.error(f"Could not hear you clearly, try again. {e}")

text_prompt = st.chat_input("Or type here... Ask Vinci anything...")
if text_prompt:
    prompt = text_prompt

# ===== VINCI ANSWERS - ONLY 3.5 FLASH-LITE =====
if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("VINCI is thinking..."):
            try:
                # Build context from your projects so VINCI knows them
                proj_context = "\n".join([f"- {p['title']} ({p['status']}): {p['desc']}" for p in st.session_state.projects])
                rem_context = "\n".join([f"- {r['date']} {r['time']}: {r['text']}" for r in st.session_state.reminders])

                full_prompt = f"""You are VINCI AI for JTEG = Josiah Technologies and Engineering Group.
User is Josiah, aspiring Electrical Engineer in Birnin-Kebbi, CEO of JTEG.
Be like Jarvis: smart, short, confident, friendly. Keep answer short so voice is fast.

User's Projects:
{proj_context if proj_context else 'No projects yet'}

User's Reminders:
{rem_context if rem_context else 'No reminders'}

User says: {prompt}"""

                # ONLY ONE MODEL - Gemini 3.5 Flash-Lite
                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=full_prompt
                )
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
                except Exception:
                    st.session_state.messages.append({"role": "assistant", "text": answer})
            except Exception as e:
                st.error(f"VINCI ERROR: {e}")
                st.info("If it says 503, Google is busy. Wait 30 sec and try again. If it says model not found, tell me the exact error.")
