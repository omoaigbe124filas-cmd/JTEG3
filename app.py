import streamlit as st
from google import genai
import speech_recognition as sr
import asyncio
import edge_tts
import io
import re
from datetime import date, time
from PIL import Image

st.set_page_config(page_title="Vinci AI", page_icon="🤖", layout="wide")

# ===== JTEG LOGO BACKGROUND + Vinci AI HANDWRITING =====
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Dancing+Script:wght@700&family=Poppins:wght@600;800&display=swap');
.stApp {
  background: linear-gradient(135deg, #0a0f1e 0%, #12233f 45%, #0f4c5c 100%);
  background-attachment: fixed;
}
.stApp::before {
  content: "JTEG";
  position: fixed;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) rotate(-12deg);
  font-family: 'Poppins', sans-serif;
  font-size: 280px;
  font-weight: 800;
  color: rgba(255,255,255,0.04);
  letter-spacing: 10px;
  z-index: 0;
  pointer-events: none;
  white-space: nowrap;
}
h1 { font-family: 'Dancing Script', cursive !important; font-size: 82px !important; font-weight: 700 !important; color: white !important; margin-bottom: 0px !important; line-height: 1 !important; text-shadow: 0 0 25px #00c6ff; }
h2, h3 { color: white !important; font-family: 'Poppins', sans-serif; }
.stCaption, p, label { color: #e0e0e0 !important; }
div[data-testid="stChatMessage"] { background: rgba(255,255,255,0.09); border-radius: 15px; padding: 10px; border: 1px solid rgba(255,255,255,0.18); }
.stButton > button { background: linear-gradient(90deg, #00c6ff, #0072ff); color: white; border: none; border-radius: 20px; font-weight: bold; }
.vinci-sub { font-family: 'Poppins', sans-serif; font-size: 16px; letter-spacing: 3px; color: #00c6ff !important; text-transform: uppercase; margin-top: 0px; }
</style>
""", unsafe_allow_html=True)

# ===== ONLY WHAT PUBLIC SHOULD SEE - Vinci AI UNCHANGED =====
st.markdown("<h1>Vinci AI</h1>", unsafe_allow_html=True)
st.markdown("<p class='vinci-sub'>Josiah Technology and Engineering Limited</p>", unsafe_allow_html=True)

# ===== DEVELOPER ONLY - HIDDEN AREA =====
with st.expander("🔒 Developer Area (Private)"):
    st.caption("This area is for Josiah only. Do not show to others.")
    st.write("Chat Model: gemini-3.5-flash-lite | Image Model: gemini-2.5-flash-image")
    st.write("Voice: en-NG-AbeoNeural - Plain Human Voice, Medium")
    st.write("Priority: 1-LIVE, 2-Voice, 3-Image Upload, 4-Typing")

MY_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not MY_KEY:
    st.error("No API Key in Secrets")
    st.stop()
client = genai.Client(api_key=MY_KEY)

# ===== VOICE - FIXED: NO SSML, NO TAGS, PLAIN CLEAN TALK =====
def clean_for_voice(text):
    # Remove ALL symbols that voice would read as slash, star, hash
    t = text.replace("*", "").replace("#", "").replace("_", "").replace("`", "").replace("<", "").replace(">", "").replace("/", " ").replace("\\", " ")
    t = re.sub(r'http\S+', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    # Keep it short so voice no go talk 1 minute for small thing
    return t[:900]

async def speak_human(text):
    clean = clean_for_voice(text)
    if not clean:
        return None
    # Plain text only. Rate medium, pitch natural. No SSML.
    for voice in ["en-NG-AbeoNeural", "en-US-GuyNeural"]:
        try:
            communicate = edge_tts.Communicate(clean, voice, rate="+10%", pitch="+2Hz")
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
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        audio_bytes = loop.run_until_complete(speak_human(text))
        loop.close()
        return audio_bytes
    except Exception:
        return None

def ask_vinci(prompt, image=None, mode="chat"):
    proj_context = "\n".join([f"- {p['title']} ({p['status']}): {p['desc']}" for p in st.session_state.projects])
    rem_context = "\n".join([f"- {r['date']} {r['time']}: {r['text']}" for r in st.session_state.reminders])
    expert = """
You are Vinci AI, expert assistant for JTEG.
JTEG = Josiah Technologies and Engineering Group. Say JTEG as one word, like Jay-Teg. NEVER spell J-T-E-G.
User is Josiah, aspiring Electrical Engineer in Birnin-Kebbi, CEO of JTEG. We go earn am together, we go build am together.
VOICE STYLE FOR SPEAKING: Speak like a human Jarvis, MEDIUM speed. Not too fast, not too slow. Use short sentences. Use comma for small pause, full stop for big pause. Ask questions with question mark, so voice go rise. End conclusions with full stop, so voice go fall. Stress important words by putting them in CAPS in your mind, but write normally. Mix clean English with small Nigerian slang naturally - Omo, Sharp sharp, No wahala, We move, You sabi - but keep professional.
IMPORTANT FOR VOICE: Never output symbols like *, #, _, <, >, /, backslash, or code in your answer. Voice will read them out. Use plain words only. No markdown symbols for voice answers. Use plain sentences.
YOU ARE MASTER OF:
- AutoCAD: 2D drawing, LINE, CIRCLE, RECTANGLE, OFFSET, TRIM, DIMENSION, LAYER, SCALE, PLOT. Give exact commands, exact dimensions in mm/inch, step-by-step.
- FreeCAD: 3D design, Sketch, Pad, Pocket, Fillet, Assembly, Export STL/DXF. Give sketch size, pad thickness, pocket depth, fillet radius.
- Proteus: ISIS circuit simulation + ARES PCB. Give components, connections, simulation result, PCB steps.
When user says Vinci, give me 3D drawing of this or give me AutoCAD drawing or give me FreeCAD, you MUST give:
1. What it is
2. Dimensions (Length x Width x Height in mm and inch)
3. Materials list
4. AutoCAD steps (commands)
5. FreeCAD steps (Sketch -> Pad -> Pocket -> Fillet)
6. Proteus steps if circuit inside
7. How to build it in real life
Keep LIVE answers SHORT 3-4 sentences, unless user asks for full design. For full design, give complete steps.
User Projects: {proj}
User Reminders: {rem}
"""
    full_prompt = expert.format(proj=proj_context if proj_context else 'No projects yet', rem=rem_context if rem_context else 'No reminders') + f"\nMode: {mode}\nUser says: {prompt}"
    if image:
        img = Image.open(image)
        response = client.models.generate_content(model="gemini-3.5-flash-lite", contents=[full_prompt, img])
    else:
        response = client.models.generate_content(model="gemini-3.5-flash-lite", contents=full_prompt)
    return response.text

# ===== IMAGE GENERATION - GEMINI 2.5 FLASH IMAGE ONLY =====
def generate_vinci_image(prompt_text, style="Product Design"):
    full_prompt = f"{style} style: {prompt_text}. High quality, detailed, professional JTEG design."
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=full_prompt
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                return part.inline_data.data, None
        for part in response.candidates[0].content.parts:
            if part.text:
                return None, part.text
        return None, "Google returned text only. Try simpler description."
    except Exception as e:
        return None, f"Image generation busy: {e}"

if "messages" not in st.session_state:
    st.session_state.messages = []
if "projects" not in st.session_state:
    st.session_state.projects = []
if "reminders" not in st.session_state:
    st.session_state.reminders = []
if "gen_images" not in st.session_state:
    st.session_state.gen_images = []
if "live_on" not in st.session_state:
    st.session_state.live_on = False

# ===== SIDEBAR - PROJECTS + REMINDERS =====
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

# ===== TABS IN YOUR PRIORITY ORDER =====
tab_live, tab_voice, tab_image, tab_design = st.tabs(["🔴 1. LIVE - Priority", "🎙️ 2. Voice", "📷 3. Image Upload", "📐 4. Design Studio - AutoCAD + FreeCAD"])

# ===== 1. LIVE =====
with tab_live:
    st.header("🔴 LIVE LAB MODE - Hands-Free")
    st.write("Your hands are busy in lab. You talk, Vinci answers, you talk again. No typing.")
    live_toggle = st.toggle("🔴 LIVE MODE ON / OFF", value=st.session_state.live_on)
    st.session_state.live_on = live_toggle
    if st.session_state.live_on:
        st.success("🟢 LIVE IS ON - Vinci is listening, Boss. Talk now.")
        for msg in st.session_state.messages[-6:]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["text"])
                if msg.get("audio"):
                    st.audio(msg["audio"])
        live_audio = st.audio_input("🎤 LIVE - Tap and talk, Vinci go answer sharp", key="live_audio")
        live_img = st.file_uploader("📷 LIVE - Show Vinci what you are holding (e.g. Itel module)", type=["jpg","jpeg","png","webp"], key="live_img")
        if live_img:
            st.image(live_img, width=350)
        if live_audio:
            with st.spinner("Vinci is listening in LIVE mode..."):
                try:
                    r = sr.Recognizer()
                    b = live_audio.read()
                    with open("temp_live.wav", "wb") as f:
                        f.write(b)
                    with sr.AudioFile("temp_live.wav") as source:
                        ad = r.record(source)
                        live_prompt = r.recognize_google(ad)
                        st.success(f"You said (LIVE): {live_prompt}")
                        st.session_state.messages.append({"role": "user", "text": f"[LIVE] {live_prompt}"})
                        with st.chat_message("assistant"):
                            answer = ask_vinci(live_prompt, live_img, mode="LIVE - SHORT, FAST, HANDS-FREE")
                            st.markdown(answer)
                            ab = speak(answer)
                            if ab:
                                st.audio(ab, format="audio/mp3", autoplay=True)
                                st.session_state.messages.append({"role": "assistant", "text": answer, "audio": ab})
                            else:
                                st.session_state.messages.append({"role": "assistant", "text": answer})
                        st.info("👆 Vinci don answer. Tap mic again to continue LIVE. Your hands free, just talk.")
                        st.rerun()
                except Exception as e:
                    st.error(f"LIVE hear problem: {e} - Try again")
    else:
        st.warning("LIVE is OFF. Turn it ON when you enter your lab.")

# ===== 2. VOICE =====
with tab_voice:
    st.header("🎙️ Voice - Smart Human Voice")
    st.write("Medium speed. Rising and falling. Stress important words. Like ChatGPT voice.")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            if msg.get("audio"):
                st.audio(msg["audio"])
    audio = st.audio_input("Tap mic and speak", key="voice_audio")
    prompt = None
    if audio:
        with st.spinner("Vinci is listening..."):
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
    if prompt:
        st.session_state.messages.append({"role": "user", "text": prompt})
        with st.chat_message("assistant"):
            answer = ask_vinci(prompt, None, mode="VOICE")
            st.markdown(answer)
            ab = speak(answer)
            if ab:
                st.audio(ab, format="audio/mp3")
                st.session_state.messages.append({"role": "assistant", "text": answer, "audio": ab})
            else:
                st.session_state.messages.append({"role": "assistant", "text": answer})

# ===== 3. IMAGE UPLOAD + GENERATION =====
with tab_image:
    st.header("📷 Image Upload + Generation")
    st.write("Upload circuit, design, Itel board, or generate new image.")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Upload & Analyse")
        up = st.file_uploader("Upload circuit, design, photo", type=["jpg","jpeg","png","webp"], key="studio_upload")
        if up:
            st.image(up, use_container_width=True)
            q = st.text_input("What should Vinci do?", value="Explain this image and tell me how to improve / build it")
            if st.button("🔍 Analyse Image"):
                with st.spinner("Vinci is looking am..."):
                    try:
                        answer = ask_vinci(q, up, mode="IMAGE ANALYSIS")
                        st.markdown(answer)
                        ab = speak(answer)
                        if ab:
                            st.audio(ab, format="audio/mp3")
                    except Exception as e:
                        st.error(f"Error: {e}")
    with col2:
        st.subheader("Generate New Image")
        img_prompt = st.text_area("Describe image", placeholder="e.g. JTEG logo, futuristic solar power bank, 12 inch casing")
        img_style = st.selectbox("Style", ["Product Design", "Realistic Photo", "Circuit Diagram", "3D Render", "Blueprint / Technical Drawing", "Logo", "FreeCAD 3D View", "AutoCAD Drawing"])
        if st.button("🎨 Generate Image", type="primary"):
            if img_prompt:
                with st.spinner("Vinci is drawing am with 2.5 Flash Image..."):
                    img_bytes, err = generate_vinci_image(img_prompt, img_style)
                    if img_bytes:
                        st.image(img_bytes, caption=img_prompt, use_container_width=True)
                        st.download_button("Download Image", data=img_bytes, file_name="vinci_jteg.png", mime="image/png")
                        st.session_state.gen_images.append(img_bytes)
                    else:
                        if err:
                            st.warning(err)
                        else:
                            st.warning("Try simpler description.")
            else:
                st.warning("Type what you want first")
    st.divider()
    st.subheader("🖼️ Your Generated Images")
    if st.session_state.gen_images:
        cols = st.columns(3)
        for idx, ib in enumerate(st.session_state.gen_images):
            with cols[idx % 3]:
                st.image(ib, use_container_width=True)
    else:
        st.caption("No images yet.")

# ===== 4. DESIGN STUDIO + TYPING =====
with tab_design:
    st.header("📐 Design Studio - Vinci Masters AutoCAD + FreeCAD")
    st.write("Talk like this: 'Vinci, give me a 3D drawing of a 12 inch solar charger casing' - Vinci go give you picture + AutoCAD steps + FreeCAD steps.")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("📐 AutoCAD - House Wiring"):
            st.session_state.design_prompt = "Give me AutoCAD drawing for house wiring plan, 2 bedroom, with dimensions, layers, commands"
    with c2:
        if st.button("🧊 FreeCAD - 12 Inch Casing"):
            st.session_state.design_prompt = "Give me FreeCAD 3D drawing of 12 inch solar charger casing, 12 inch x 8 inch x 2 inch, with battery space, USB hole, screen hole. Give AutoCAD + FreeCAD steps"
    with c3:
        if st.button("⚡ Proteus - Solar Charger Circuit"):
            st.session_state.design_prompt = "Give me Proteus circuit for solar charger, solar panel to battery to USB 5V, components, connections, simulation"
    design_text = st.text_area("Describe what you want Vinci to design", value=st.session_state.get("design_prompt", "Give me a 3D drawing of a 12 inch JTEG solar charger casing"), height=100)
    if st.button("✨ Generate Design + Drawing", type="primary"):
        with st.spinner("Vinci is designing am like engineer..."):
            try:
                answer = ask_vinci(design_text, None, mode="FULL DESIGN - AutoCAD + FreeCAD + Proteus - GIVE DIMENSIONS, COMMANDS, STEPS")
                st.markdown(answer)
                img_bytes, err = generate_vinci_image(design_text, "Blueprint / Technical Drawing")
                if img_bytes:
                    st.image(img_bytes, caption="Vinci 3D Design", use_container_width=True)
                    st.download_button("Download Design", data=img_bytes, file_name="vinci_design.png", mime="image/png")
                elif err:
                    st.info(err)
                ab = speak("I don design am for you, boss. Check the dimensions and steps. We go build am together.")
                if ab:
                    st.audio(ab, format="audio/mp3")
            except Exception as e:
                st.error(f"Error: {e}")
    st.divider()
    st.subheader("💬 Typing Chat - Type Here")
    text_prompt = st.chat_input("Or type here... Ask Vinci anything...")
    if text_prompt:
        st.session_state.messages.append({"role": "user", "text": text_prompt})
        with st.chat_message("assistant"):
            answer = ask_vinci(text_prompt, None, mode="TYPING")
            st.markdown(answer)
            ab = speak(answer)
            if ab:
                st.audio(ab, format="audio/mp3")
                st.session_state.messages.append({"role": "assistant", "text": answer, "audio": ab})
            else:
                st.session_state.messages.append({"role": "assistant", "text": answer})
