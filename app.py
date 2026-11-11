import streamlit as st
from google import genai
import speech_recognition as sr
import asyncio
import edge_tts
import io
from datetime import datetime, date, time
from PIL import Image
import base64

st.set_page_config(page_title="VINCI - JTEG", page_icon="🤖", layout="wide")

# ===== BEAUTIFUL BACKGROUND =====
st.markdown("""
<style>
.stApp { background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%); background-attachment: fixed; }
h1, h2, h3 { color: white !important; }
.stCaption, p, label { color: #e0e0e0 !important; }
div[data-testid="stChatMessage"] { background: rgba(255,255,255,0.08); border-radius: 15px; padding: 10px; border: 1px solid rgba(255,255,255,0.15); }
.stButton > button { background: linear-gradient(90deg, #00c6ff, #0072ff); color: white; border: none; border-radius: 20px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🤖 VINCI AI - JTEG | JARVIS MODE")
st.caption("Josiah Technologies and Engineering Group | CEO: Josiah | Birnin-Kebbi | Model: Gemini 3.5 Flash-Lite ONLY | Voice: Nigerian Male Jarvis")

MY_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not MY_KEY:
    st.error("No API Key in Secrets")
    st.stop()

client = genai.Client(api_key=MY_KEY)

# ===== MALE JARVIS VOICE - NIGERIAN MALE, FAST =====
async def speak_male_fast(text):
    # en-NG-AbeoNeural = Nigerian Male, rate +35% = fast like Jarvis
    # Fallback to US Jarvis male if Naija voice fails
    for voice, rate in [("en-NG-AbeoNeural", "+35%"), ("en-US-GuyNeural", "+30%")]:
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch="+5Hz")
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_fp.write(chunk["data"])
            mp3_fp.seek(0)
            return mp3_fp.getvalue()
        except Exception:
            continue
    return None

def speak(text):
    # Clean text for voice - short, fast
    clean = text.replace("*", "").replace("#", "").replace("_", "")[:800]
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        audio_bytes = loop.run_until_complete(speak_male_fast(clean))
        loop.close()
        return audio_bytes
    except Exception:
        return None

if "messages" not in st.session_state:
    st.session_state.messages = []
if "projects" not in st.session_state:
    st.session_state.projects = []
if "reminders" not in st.session_state:
    st.session_state.reminders = []
if "gen_images" not in st.session_state:
    st.session_state.gen_images = []

# ===== SIDEBAR =====
with st.sidebar:
    st.header("📁 My Projects - JTEG")
    proj_title = st.text_input("Project Name", placeholder="e.g. Smart Solar Charger")
    proj_desc = st.text_area("Project Details", placeholder="What is it? Materials? Progress?")
    proj_status = st.selectbox("Status", ["Idea 💡", "In Progress 🔨", "Done ✅", "Paused ⏸️"])
    if st.button("Save Project"):
        if proj_title:
            st.session_state.projects.append({"title": proj_title, "desc": proj_desc, "status": proj_status, "date": str(date.today())})
            st.success(f"Saved: {proj_title}")
            st.rerun()

    st.divider()
    for i, p in enumerate(st.session_state.projects):
        with st.expander(f"{p['status']} - {p['title']}"):
            st.write(p['desc'])
            if st.button(f"Delete", key=f"del_proj_{i}"):
                st.session_state.projects.pop(i)
                st.rerun()

    st.divider()
    st.header("⏰ Reminders")
    rem_text = st.text_input("Reminder", placeholder="e.g. Charge battery")
    rem_date = st.date_input("Date", value=date.today())
    rem_time = st.time_input("Time", value=time(8, 0))
    if st.button("Set Reminder"):
        if rem_text:
            st.session_state.reminders.append({"text": rem_text, "date": str(rem_date), "time": str(rem_time)})
            st.success("Reminder set!")
            st.rerun()
    for i, r in enumerate(st.session_state.reminders):
        st.info(f"⏰ {r['date']} {r['time']} - {r['text']}")
        if st.button(f"Done", key=f"del_rem_{i}"):
            st.session_state.reminders.pop(i)
            st.rerun()

    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.rerun()

# ===== TABS: CHAT | IMAGE STUDIO =====
tab1, tab2 = st.tabs(["💬 Chat with VINCI", "🎨 Image Generation & Upload"])

with tab1:
    # Reminders today
    today_str = str(date.today())
    todays = [r for r in st.session_state.reminders if r['date'] == today_str]
    if todays:
        st.warning(f"🔔 {len(todays)} reminder(s) today!")
        for r in todays:
            st.write(f"⏰ {r['time']} - {r['text']}")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            if msg.get("audio"):
                st.audio(msg["audio"])
            if msg.get("image"):
                st.image(msg["image"], width=350)

    st.markdown("### 🎤 Talk to VINCI")
    audio = st.audio_input("Tap mic and speak")
    prompt = None
    uploaded_for_chat = st.file_uploader("📷 Upload image for VINCI to see (optional)", type=["jpg","jpeg","png","webp"], key="chat_upload")

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

    if prompt or (uploaded_for_chat and st.button("Ask VINCI about this image")):
        if not prompt and uploaded_for_chat:
            prompt = "Explain what you see in this image in detail, like Jarvis. If it is a circuit, design, or project, give dimensions, parts, and how to build/improve it."
        
        st.session_state.messages.append({"role": "user", "text": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            if uploaded_for_chat:
                st.image(uploaded_for_chat, width=350)

        with st.chat_message("assistant"):
            with st.spinner("VINCI is thinking fast..."):
                try:
                    proj_context = "\n".join([f"- {p['title']} ({p['status']}): {p['desc']}" for p in st.session_state.projects])
                    rem_context = "\n".join([f"- {r['date']} {r['time']}: {r['text']}" for r in st.session_state.reminders])

                    # VINCI PERSONA - JARVIS MALE, NAIJA SLANG, FAST
                    full_prompt = f"""You are VINCI AI, Jarvis for JTEG.
JTEG = Josiah Technologies and Engineering Group. NEVER say J-T-E-G letter by letter. Say 'JTEG' as one word, like 'Jay-Teg'.
User is Josiah, aspiring Electrical Engineer in Birnin-Kebbi, CEO of JTEG. We go earn am together, we go build am together.
Speak like Jarvis: confident, sharp, male, fast, smart. Mix clean English with small Nigerian slang naturally - like 'Omo', 'Sharp sharp', 'No wahala', 'We move', 'You sabi', 'E choke' - but keep it professional and clear.
Pronounce Nigerian names well: Josiah (Jo-SY-ah), Birnin-Kebbi, Kebbi, Josiah Technologies.
Keep answer SHORT and FAST for voice. Max 5 short sentences unless user asks for full design. For designs, give dimensions, materials, parts list, step-by-step.
User's Projects: {proj_context if proj_context else 'No projects yet'}
User's Reminders: {rem_context if rem_context else 'No reminders'}
User says: {prompt}"""

                    # IMAGE + TEXT
                    if uploaded_for_chat:
                        img = Image.open(uploaded_for_chat)
                        response = client.models.generate_content(
                            model="gemini-3.5-flash-lite",
                            contents=[full_prompt, img]
                        )
                    else:
                        response = client.models.generate_content(
                            model="gemini-3.5-flash-lite",
                            contents=full_prompt
                        )
                    answer = response.text
                    st.markdown(answer)

                    # MALE FAST VOICE
                    audio_bytes = speak(answer)
                    if audio_bytes:
                        st.audio(audio_bytes, format="audio/mp3")
                        st.session_state.messages.append({"role": "assistant", "text": answer, "audio": audio_bytes})
                    else:
                        st.session_state.messages.append({"role": "assistant", "text": answer})
                except Exception as e:
                    st.error(f"VINCI ERROR: {e}")

with tab2:
    st.header("🎨 VINCI Image Studio")
    st.write("Generate images, or upload your own design / circuit / photo and VINCI will analyse am.")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("1. Generate New Image")
        img_prompt = st.text_area("Describe image", placeholder="e.g. Futuristic solar power bank designed by JTEG, sleek black and blue, product design, studio lighting")
        img_style = st.selectbox("Style", ["Product Design", "Realistic Photo", "Circuit Diagram", "3D Render", "Blueprint / Technical Drawing", "Logo"])
        if st.button("🎨 Generate Image", type="primary"):
            if img_prompt:
                with st.spinner("VINCI is drawing am sharp sharp..."):
                    try:
                        # Use Gemini image model for generation
                        full_img_prompt = f"{img_style} style: {img_prompt}. High quality, detailed, professional JTEG design."
                        response = client.models.generate_content(
                            model="gemini-2.0-flash-preview-image-generation",
                            contents=full_img_prompt
                        )
                        # Try to extract image
                        found = False
                        for part in response.candidates[0].content.parts:
                            if part.inline_data is not None:
                                img_bytes = part.inline_data.data
                                st.image(img_bytes, caption=img_prompt, use_container_width=True)
                                st.download_button("Download Image", data=img_bytes, file_name="vinci_jteg.png", mime="image/png")
                                st.session_state.gen_images.append(img_bytes)
                                found = True
                            elif part.text:
                                st.markdown(part.text)
                        if not found:
                            st.warning("Google returned text only for this prompt. Try again with simpler description.")
                            # Speak fallback
                            audio_b = speak("I don try draw am, but Google return text only. Try again with simpler description.")
                            if audio_b:
                                st.audio(audio_b, format="audio/mp3")
                    except Exception as e:
                        st.error(f"Image generation busy: {e}")
                        st.info("Tip: If this model is busy, use the chat tab to describe the design in words first, then try again.")
            else:
                st.warning("Type what you want VINCI to draw first")

    with col2:
        st.subheader("2. Upload & Analyse Image")
        up = st.file_uploader("Upload circuit, design, photo", type=["jpg","jpeg","png","webp"], key="studio_upload")
        if up:
            st.image(up, use_container_width=True)
            q = st.text_input("What should VINCI do with this image?", value="Explain this image and tell me how to improve / build it")
            if st.button("🔍 Analyse Image"):
                with st.spinner("VINCI is looking am..."):
                    try:
                        img = Image.open(up)
                        resp = client.models.generate_content(
                            model="gemini-3.5-flash-lite",
                            contents=[f"You are VINCI Jarvis for JTEG. User is Josiah. Analyse this image like Jarvis, fast, sharp, with Nigerian slang small. {q}. If circuit/design, give parts, dimensions, improvements, step-by-step.", img]
                        )
                        st.markdown(resp.text)
                        ab = speak(resp.text)
                        if ab:
                            st.audio(ab, format="audio/mp3")
                    except Exception as e:
                        st.error(f"Error: {e}")

    st.divider()
    st.subheader("🖼️ Your Generated Images")
    if st.session_state.gen_images:
        cols = st.columns(3)
        for idx, ib in enumerate(st.session_state.gen_images):
            with cols[idx % 3]:
                st.image(ib, use_container_width=True)
    else:
        st.caption("No images yet. Generate one above.")
