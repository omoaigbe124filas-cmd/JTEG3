import streamlit as st
from google import genai
import speech_recognition as sr
import asyncio
import edge_tts
import io
import re
import streamlit.components.v1 as components
from datetime import date, time
from PIL import Image
import base64
import urllib.parse
import urllib.request

st.set_page_config(page_title="Vinci AI", page_icon="🤖", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Dancing+Script:wght@700&family=Poppins:wght@600;800&display=swap');
.stApp { background: linear-gradient(135deg, #0a0f1e 0%, #12233f 45%, #0f4c5c 100%); background-attachment: fixed; }
.stApp::before { content: "JTEG"; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(-12deg); font-family: 'Poppins', sans-serif; font-size: 280px; font-weight: 800; color: rgba(255,255,255,0.04); letter-spacing: 10px; z-index: 0; pointer-events: none; white-space: nowrap; }
h1 { font-family: 'Dancing Script', cursive !important; font-size: 82px !important; font-weight: 700 !important; color: white !important; margin-bottom: 0px !important; line-height: 1 !important; text-shadow: 0 0 25px #00c6ff; }
h2, h3 { color: white !important; font-family: 'Poppins', sans-serif; }
.stCaption, p, label { color: #e0e0e0 !important; }
div[data-testid="stChatMessage"] { background: rgba(255,255,255,0.09); border-radius: 15px; padding: 10px; border: 1px solid rgba(255,255,255,0.18); }
.stButton > button { background: linear-gradient(90deg, #00c6ff, #0072ff); color: white; border: none; border-radius: 20px; font-weight: bold; }
.vinci-sub { font-family: 'Poppins', sans-serif; font-size: 16px; letter-spacing: 3px; color: #00c6ff !important; text-transform: uppercase; margin-top: 0px; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1>Vinci AI</h1>", unsafe_allow_html=True)
st.markdown("<p class='vinci-sub'>Josiah Technology and Engineering Limited</p>", unsafe_allow_html=True)

with st.expander("🔒 Developer Area (Private)"):
    st.caption("Josiah only. Chat: gemini-3.5-flash-lite | Image: Pollinations Free - No Quota")
    st.write("Priority: 1-Chat, 2-LIVE, 3-Image, 4-Design Studio, 5-Video")

MY_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not MY_KEY:
    st.error("No API Key in Secrets")
    st.stop()
client = genai.Client(api_key=MY_KEY)

def clean_for_voice(text):
    t = text.replace("*", "").replace("#", "").replace("_", "").replace("`", "").replace("<", "").replace(">", "").replace("/", " ").replace("\\", " ")
    t = re.sub(r'http\S+', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:900]

async def speak_human(text):
    clean = clean_for_voice(text)
    if not clean:
        return None
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
        b = loop.run_until_complete(speak_human(text))
        loop.close()
        return b
    except Exception:
        return None

def ask_vinci(prompt, image=None, mode="chat"):
    proj = ""
    for p in st.session_state.projects:
        proj = proj + "- " + p["title"] + " (" + p["status"] + "): " + p["desc"] + "\n"
    rem = ""
    for r in st.session_state.reminders:
        rem = rem + "- " + r["date"] + " " + r["time"] + ": " + r["text"] + "\n"
    expert = "You are Vinci AI, Jarvis for JTEG. Say JTEG as one word Jay-Teg. Never spell J-T-E-G. "
    expert = expert + "User is Josiah, Electrical Engineer in Birnin-Kebbi, CEO of JTEG. We go earn am together. "
    expert = expert + "Speak human, MEDIUM speed. Short sentences. Comma for small pause, full stop for big pause. Question mark for rising voice. No symbols like star hash slash in answer. Plain words only. "
    expert = expert + "Master of AutoCAD, FreeCAD, Proteus. When user asks design, give Dimensions, Materials, AutoCAD steps, FreeCAD steps, Proteus steps, How to build. "
    expert = expert + "Projects: " + proj + " Reminders: " + rem + " Mode: " + mode + " User: " + prompt
    if image:
        img = Image.open(image)
        resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=[expert, img])
    else:
        resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=expert)
    return resp.text

def generate_vinci_image(prompt_text, style="Product Design"):
    try:
        full = style + ", " + prompt_text + ", high quality, detailed, professional JTEG design, clean background"
        encoded = urllib.parse.quote(full)
        url = "https://image.pollinations.ai/prompt/" + encoded + "?width=1024&height=1024&seed=42&nologo=true&model=flux"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            img_bytes = resp.read()
        if len(img_bytes) > 1000:
            return img_bytes, None
        else:
            return None, "Image engine busy, try again in 5 seconds."
    except Exception as e:
        return None, "Image engine busy: " + str(e)

def show_svg(svg_code, filename="vinci_design.svg"):
    b64 = base64.b64encode(svg_code.encode()).decode()
    st.markdown('<img src="data:image/svg+xml;base64,' + b64 + '" style="width:100%;background:white;border-radius:12px;padding:5px;">', unsafe_allow_html=True)
    st.download_button("Download Drawing (SVG)", data=svg_code, file_name=filename, mime="image/svg+xml")

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

with st.sidebar:
    st.header("📁 My Projects - JTEG")
    proj_title = st.text_input("Project Name", placeholder="e.g. Smart Solar Charger")
    proj_desc = st.text_area("Project Details")
    proj_status = st.selectbox("Status", ["Idea 💡", "In Progress 🔨", "Done ✅", "Paused ⏸️"])
    if st.button("Save Project"):
        if proj_title:
            st.session_state.projects.append({"title": proj_title, "desc": proj_desc, "status": proj_status, "date": str(date.today())})
            st.success("Saved")
            st.rerun()
    for i, p in enumerate(st.session_state.projects):
        with st.expander(p["status"] + " - " + p["title"]):
            st.write(p["desc"])
            if st.button("Delete", key="delp" + str(i)):
                st.session_state.projects.pop(i)
                st.rerun()
    st.divider()
    st.header("⏰ Reminders")
    rem_text = st.text_input("Reminder")
    rem_date = st.date_input("Date", value=date.today())
    rem_time = st.time_input("Time", value=time(8, 0))
    if st.button("Set Reminder"):
        if rem_text:
            st.session_state.reminders.append({"text": rem_text, "date": str(rem_date), "time": str(rem_time)})
            st.rerun()
    for i, r in enumerate(st.session_state.reminders):
        st.info("⏰ " + r["date"] + " " + r["time"] + " - " + r["text"])
        if st.button("Done", key="delr" + str(i)):
            st.session_state.reminders.pop(i)
            st.rerun()

tab_chat, tab_live, tab_image, tab_design, tab_video = st.tabs(["💬 1. CHAT", "🔴 2. LIVE", "🎨 3. IMAGE", "📐 4. DESIGN STUDIO", "🎬 5. VIDEO"])

with tab_chat:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            if msg.get("audio"):
                st.audio(msg["audio"])
    st.markdown("### Type or Talk - side by side")
    col_t, col_m = st.columns([4, 1])
    with col_t:
        text_prompt = st.chat_input("Type your message here... Ask Vinci anything...")
    with col_m:
        st.caption("🎤 Voice")
        audio = st.audio_input("Tap mic", key="chat_mic")
    prompt = None
    img_chat = st.file_uploader("📷 Upload image (optional)", type=["jpg", "jpeg", "png", "webp"], key="chat_up")
    if img_chat:
        st.image(img_chat, width=300)
    if audio:
        try:
            r = sr.Recognizer()
            b = audio.read()
            open("temp.wav", "wb").write(b)
            with sr.AudioFile("temp.wav") as src:
                ad = r.record(src)
                prompt = r.recognize_google(ad)
                st.success("You said: " + prompt)
        except Exception as e:
            st.error("Could not hear: " + str(e))
    if text_prompt:
        prompt = text_prompt
    if prompt or (img_chat and st.button("Ask Vinci about this image")):
        if not prompt:
            prompt = "Explain this image in detail, like Jarvis. If circuit or design, give parts, dimensions, how to build or improve."
        st.session_state.messages.append({"role": "user", "text": prompt})
        with st.chat_message("assistant"):
            try:
                answer = ask_vinci(prompt, img_chat, "CHAT")
                st.markdown(answer)
                ab = speak(answer)
                if ab:
                    st.audio(ab, format="audio/mp3")
                    st.session_state.messages.append({"role": "assistant", "text": answer, "audio": ab})
                else:
                    st.session_state.messages.append({"role": "assistant", "text": answer})
            except Exception as e:
                st.error("Error: " + str(e))

with tab_live:
    st.header("🔴 LIVE - Real Jarvis Mode")
    live_on = st.toggle("🔴 LIVE MASTER SWITCH - ON / OFF", value=st.session_state.get("live_on", False), key="live_master_toggle")
    st.session_state.live_on = live_on
    if not live_on:
        st.warning("⏹️ LIVE IS OFF - Vinci is quiet now. E no dey listen. Turn switch ON when you want am again.")
    else:
        st.success("🟢 LIVE IS ON - Vinci dey listen for Vinci")
        st.caption("To turn OFF: Flip MASTER SWITCH above to OFF. Vinci go stop immediately.")
        live_html = open_live_html()
        components.html(live_html, height=420)
        st.divider()
        st.subheader("LIVE with Gemini Brain (Backup)")
        live_audio2 = st.audio_input("Backup - tap and talk", key="live_backup")
        if live_audio2:
            try:
                r = sr.Recognizer()
                b = live_audio2.read()
                open("temp2.wav", "wb").write(b)
                with sr.AudioFile("temp2.wav") as src:
                    ad = r.record(src)
                    lp = r.recognize_google(ad)
                    st.success("You said: " + lp)
                    ans = ask_vinci(lp, None, "LIVE - SHORT")
                    st.markdown(ans)
                    ab = speak(ans)
                    if ab:
                        st.audio(ab, format="audio/mp3", autoplay=True)
            except Exception as e:
                st.error(str(e))

with tab_image:
    st.header("🎨 IMAGE - Pollinations Free, No Quota, No Payment")
    st.caption("Chat still uses Gemini 3.5 Flash-Lite. Image uses Pollinations Flux - free unlimited.")
    img_prompt = st.text_area("Describe image", placeholder="e.g. JTEG solar power bank, black and blue, Blue")
    img_style = st.selectbox("Style", ["Product Design", "Realistic Photo", "Circuit Diagram", "3D Render", "Blueprint / Technical Drawing", "Logo"])
    if st.button("🎨 Generate Image", type="primary"):
        if img_prompt:
            with st.spinner("Vinci is drawing am with Pollinations..."):
                img_bytes, err = generate_vinci_image(img_prompt, img_style)
                if img_bytes:
                    st.image(img_bytes, caption=img_prompt, use_container_width=True)
                    st.download_button("Download", data=img_bytes, file_name="vinci_jteg.png", mime="image/png")
                    st.session_state.gen_images.append(img_bytes)
                else:
                    st.warning(err)
        else:
            st.warning("Type first")
    st.divider()
    for idx, ib in enumerate(st.session_state.gen_images):
        st.image(ib, width=300)

with tab_design:
    st.header("📐 DESIGN STUDIO - Your AutoCAD + FreeCAD + Proteus Inside Vinci")
    st.write("No need install AutoCAD. No need install FreeCAD. No need install Proteus. Everything dey here.")
    design_choice = st.selectbox("Choose Simulator", ["🏠 AutoCAD - House Wiring & House Plan", "🧊 FreeCAD - 3D Casing / Product Box", "⚡ Proteus - PCB & Circuit Simulator"])
    if design_choice.startswith("🏠"):
        st.subheader("🏠 AutoCAD Simulator - House Wiring & House Plan")
        c1, c2, c3 = st.columns(3)
        with c1:
            house_len = st.slider("House Length (feet)", 20, 80, 40)
            house_breadth = st.slider("House Breadth / Width (feet)", 20, 60, 30)
            num_rooms = st.slider("Number of Rooms", 1, 6, 3)
        with c2:
            num_windows = st.slider("Number of Windows", 1, 10, 4)
            num_doors = st.slider("Number of Doors", 1, 5, 2)
            num_sockets = st.slider("Number of Sockets", 2, 20, 8)
        with c3:
            num_lights = st.slider("Number of Lights / Bulbs", 1, 15, 6)
            num_switches = st.slider("Number of Switches", 1, 15, 6)
            wire_type = st.selectbox("Wiring Type", ["Concealed Wiring (inside wall)", "Surface Wiring (on wall)", "Solar + Grid Hybrid"])
        line_len = st.slider("Line Length for extra wall (feet)", 0, 20, 10)
        line_pos = st.selectbox("Where to draw line?", ["Middle Partition - Vertical", "Middle Partition - Horizontal", "No Extra Line"])
        if st.button("✨ Draw House Plan Now", type="primary"):
            W = house_len * 10
            H = house_breadth * 10
            scale = 700 / max(W, 10)
            dw = int(W * scale)
            dh = int(H * scale)
            room_w = dw // max(num_rooms, 1)
            svg_parts = []
            svg_parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="750" height="550" viewBox="0 0 750 550" style="background:white;border-radius:12px">')
            svg_parts.append('<text x="20" y="25" font-family="Arial" font-size="20" font-weight="bold" fill="#0f2027">JTEG HOUSE PLAN - ' + str(house_len) + 'ft x ' + str(house_breadth) + 'ft</text>')
            svg_parts.append('<text x="20" y="45" font-family="Arial" font-size="12" fill="#0072ff">AutoCAD Simulator | Length: ' + str(house_len) + 'ft | Breadth: ' + str(house_breadth) + 'ft | Type: ' + wire_type + '</text>')
            svg_parts.append('<rect x="30" y="60" width="' + str(dw) + '" height="' + str(dh) + '" fill="#f5f5f5" stroke="black" stroke-width="4"/>')
            for i in range(num_rooms):
                x = 30 + i * room_w
                svg_parts.append('<rect x="' + str(x) + '" y="60" width="' + str(room_w) + '" height="' + str(dh) + '" fill="none" stroke="#333" stroke-width="2"/>')
                svg_parts.append('<text x="' + str(x + 10) + '" y="80" font-family="Arial" font-size="12" font-weight="bold">ROOM ' + str(i + 1) + '</text>')
                svg_parts.append('<circle cx="' + str(x + room_w // 2) + '" cy="' + str(60 + dh // 2 - 20) + '" r="10" fill="yellow" stroke="black"/>')
                svg_parts.append('<rect x="' + str(x + 10) + '" y="' + str(60 + dh - 30) + '" width="14" height="10" fill="white" stroke="red"/>')
            for i in range(num_windows):
                wx = 50 + i * (dw // max(num_windows, 1))
                svg_parts.append('<rect x="' + str(wx) + '" y="56" width="30" height="8" fill="#00c6ff" stroke="blue"/>')
            for i in range(num_doors):
                dx = 60 + i * (dw // max(num_doors, 1))
                svg_parts.append('<rect x="' + str(dx) + '" y="' + str(60 + dh - 2) + '" width="35" height="8" fill="#8B4513"/>')
            if line_pos != "No Extra Line":
                if "Vertical" in line_pos:
                    svg_parts.append('<line x1="' + str(30 + dw // 2) + '" y1="60" x2="' + str(30 + dw // 2) + '" y2="' + str(60 + dh) + '" stroke="red" stroke-width="2" stroke-dasharray="6,4"/>')
                else:
                    svg_parts.append('<line x1="30" y1="' + str(60 + dh // 2) + '" x2="' + str(30 + dw) + '" y2="' + str(60 + dh // 2) + '" stroke="red" stroke-width="2" stroke-dasharray="6,4"/>')
            svg_parts.append('<text x="20" y="540" font-family="Arial" font-size="12" fill="#333">Lights: ' + str(num_lights) + ' | Switches: ' + str(num_switches) + ' | Sockets: ' + str(num_sockets) + ' | Windows: ' + str(num_windows) + ' | Doors: ' + str(num_doors) + '</text>')
            svg_parts.append('</svg>')
            svg_code = "".join(svg_parts)
            show_svg(svg_code, "vinci_house_plan.svg")
            st.success("House Plan Done! " + str(house_len) + "ft x " + str(house_breadth) + "ft")
            st.info("AutoCAD: LINE 0,0 to " + str(house_len) + "ft | RECTANGLE " + str(house_len) + "ft x " + str(house_breadth) + "ft | OFFSET 0.5ft for wall | DIMENSION for length and breadth")
            st.info("Materials: Cable 1.5mm for lights, Cable 2.5mm for sockets, Switches " + str(num_switches) + ", Sockets " + str(num_sockets))
    elif design_choice.startswith("🧊"):
        st.subheader("🧊 FreeCAD Simulator - 3D Casing / Product Box")
        c1, c2 = st.columns(2)
        with c1:
            f_len = st.slider("Length (inch)", 2, 24, 12)
            f_wid = st.slider("Width / Breadth (inch)", 2, 16, 8)
            f_hei = st.slider("Height / Thickness (inch)", 1, 6, 2)
            f_product = st.selectbox("Product", ["Solar Charger Casing", "Power Bank Box", "Vinci Tablet Stand", "JTEG Control Box", "Custom Box"])
        with c2:
            f_battery = st.checkbox("Battery Space Inside?", value=True)
            f_usb = st.checkbox("USB Hole?", value=True)
            f_screen = st.checkbox("Screen / Display Hole?", value=True)
            f_fillet = st.slider("Fillet - Round Edge (inch)", 0.0, 1.0, 0.2)
        if st.button("✨ Draw 3D Casing Now", type="primary"):
            L = f_len * 28
            W = f_wid * 28
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="750" height="480" viewBox="0 0 750 480" style="background:white;border-radius:12px">'
            svg = svg + '<text x="20" y="25" font-family="Arial" font-size="20" font-weight="bold" fill="#0f2027">' + f_product + ' - FreeCAD Simulator</text>'
            svg = svg + '<text x="20" y="45" font-family="Arial" font-size="12" fill="#0072ff">Length ' + str(f_len) + ' inch x Width ' + str(f_wid) + ' inch x Height ' + str(f_hei) + ' inch</text>'
            svg = svg + '<rect x="80" y="80" width="' + str(L) + '" height="' + str(W) + '" fill="#0f2027" stroke="#00c6ff" stroke-width="3"/>'
            svg = svg + '<rect x="100" y="100" width="' + str(L - 40) + '" height="' + str(W - 40) + '" fill="none" stroke="#ff9900" stroke-width="1.5" stroke-dasharray="6,4"/>'
            svg = svg + '<text x="100" y="120" font-family="Arial" font-size="14" fill="white">JTEG - ' + f_product + '</text>'
            svg = svg + '<circle cx="' + str(80 + L - 30) + '" cy="110" r="14" fill="#00c6ff"/>'
            svg = svg + '<rect x="110" y="140" width="110" height="60" fill="#00c6ff" opacity="0.25" stroke="#0072ff"/>'
            svg = svg + '<text x="115" y="170" font-size="12">BATTERY SPACE</text>'
            svg = svg + '<line x1="80" y1="' + str(80 + W + 20) + '" x2="' + str(80 + L) + '" y2="' + str(80 + W + 20) + '" stroke="red" stroke-width="2"/>'
            svg = svg + '<text x="20" y="460" font-size="12">Battery: ' + str(f_battery) + ' | USB: ' + str(f_usb) + ' | Screen: ' + str(f_screen) + '</text>'
           
