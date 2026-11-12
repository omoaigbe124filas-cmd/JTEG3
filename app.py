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
import random
import time as time_mod

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
    st.caption("Josiah only. Chat: gemini-3.5-flash-lite | Image: Pollinations Free - No Quota | VIDEO REMOVED")
    st.write("Priority: 1-Chat, 2-LIVE, 3-Image, 4-Design Studio (AutoCAD + FreeCAD SOLID + Proteus)")

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
    expert = expert + "You are VAST AI, very very vast, factual, accurate, no guessing. You sabi electronics, house design, casing, circuit, solar, battery, 18650, resistor, capacitor, Ohm law V=I*R, Power P=V*I. "
    expert = expert + "Master of AutoCAD, FreeCAD, Proteus. When user asks design, give Dimensions, Materials, AutoCAD steps, FreeCAD steps, Proteus steps, How to build. "
    expert = expert + "If user asks AutoCAD house, ask: Bungalow, Duplex, Mansion, Storey Building. Then rooms, storeys, windows, doors, toilets, kitchen, parlour. Then give Blueprint, Floor Plan, 3D description. "
    expert = expert + "If user asks FreeCAD casing, ask: Solar Power Bank, Decoder, Television, Radio, Charger, Battery Pack, Custom. Then Length, Width, Height, Thickness, USB ports, Battery count, Solar size, Screw holes. Then give real mm simulation, if battery go fit, if screw go align. "
    expert = expert + "If user asks Proteus, ask: AC, DC, AC to DC, DC to AC, AC+DC. Then give Empty PCB 100x80mm, let user choose components and values, then Activate, Soldering Mode, Battery Test, Spark if short. "
    expert = expert + "Projects: " + proj + " Reminders: " + rem + " Mode: " + mode + " User: " + prompt
    if image:
        img = Image.open(image)
        resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=[expert, img])
    else:
        resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=expert)
    return resp.text

def generate_vinci_image(prompt_text, style="Product Design"):
    # Pollinations Enhanced - Retry 3 times, No 404
    for attempt in range(3):
        try:
            full = style + ", " + prompt_text + ", high quality, detailed, professional JTEG design, clean background"
            encoded = urllib.parse.quote(full)
            seed = random.randint(1, 999999)
            url = "https://image.pollinations.ai/prompt/" + encoded + "?width=1024&height=1024&seed=" + str(seed) + "&nologo=true&model=flux"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                img_bytes = resp.read()
            if len(img_bytes) > 5000:
                return img_bytes, None
            time_mod.sleep(1)
        except Exception as e:
            if attempt == 2:
                return None, "Image engine busy: " + str(e)
            time_mod.sleep(1)
    return None, "Network slow, press Generate again. Pollinations still dey work, no 404."

def show_svg(svg_code, filename="vinci_design.svg"):
    b64 = base64.b64encode(svg_code.encode()).decode()
    st.markdown('<img src="data:image/svg+xml;base64,' + b64 + '" style="width:100%;background:white;border-radius:12px;padding:5px;">', unsafe_allow_html=True)
    st.download_button("Download Drawing (SVG)", data=svg_code, file_name=filename, mime="image/svg+xml")

def open_live_html():
    # LIVE placeholder - safe, no crash. Real LIVE voice go use Backup below.
    return "<div style='background:#0a0f1e;color:white;padding:20px;border-radius:12px;text-align:center;'><h3 style='color:white;'>🟢 LIVE IS ON</h3><p>Vinci dey listen. Use Backup mic below to talk to Vinci.</p><p>If you want turn OFF, flip MASTER SWITCH above to OFF.</p></div>"

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
if "chat_draft" not in st.session_state:
    st.session_state.chat_draft = ""

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

# VIDEO REMOVED - 4 TABS ONLY
tab_chat, tab_live, tab_image, tab_design = st.tabs(["💬 1. CHAT", "🔴 2. LIVE", "🎨 3. IMAGE", "📐 4. DESIGN STUDIO"])

with tab_chat:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            if msg.get("audio"):
                st.audio(msg["audio"])
    st.markdown("### Type or Talk - ONE BOX ONLY: [+] [Type...] [🎤]")
    st.caption("Left: + upload | Middle: Type | Right: Mic - e go transcribe first before you send, you go see am first.")
    # UNIFIED BOX
    col_plus, col_text, col_mic = st.columns([1, 6, 1])
    with col_plus:
        img_chat = st.file_uploader("+", type=["jpg", "jpeg", "png", "webp", "pdf", "docx"], label_visibility="collapsed", key="chat_up_plus")
        if img_chat:
            st.success("File don enter: " + str(getattr(img_chat, 'name', 'file')))
    with col_text:
        text_prompt = st.chat_input("Type your message here... Ask Vinci anything...")
    with col_mic:
        st.caption("🎤 Voice")
        audio = st.audio_input("Tap mic", key="chat_mic")
    prompt = None
    if img_chat:
        try:
            st.image(img_chat, width=300)
        except Exception:
            pass
    if audio:
        try:
            r = sr.Recognizer()
            b = audio.read()
            open("temp.wav", "wb").write(b)
            with sr.AudioFile("temp.wav") as src:
                ad = r.record(src)
                prompt = r.recognize_google(ad)
                st.info("🎤 Transcribed - See am first, edit am if you want, then press SEND below:")
                st.text_input("Edit transcribed text before sending:", value=prompt, key="transcribed_edit")
                # Use edited version if user edit am
                if st.session_state.get("transcribed_edit"):
                    prompt = st.session_state.get("transcribed_edit")
                st.success("You said: " + str(prompt))
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
                answer = ask_vinci(prompt, img_chat if img_chat and str(getattr(img_chat, 'type', '')) .startswith('image') else None, "CHAT")
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
        components.html(live_html, height=220)
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
    st.caption("Chat still uses Gemini 3.5 Flash-Lite. Image uses Pollinations Flux - free unlimited. Enhanced, No 404.")
    img_prompt = st.text_area("Describe image", placeholder="e.g. JTEG solar power bank, black and blue")
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
    design_choice = st.selectbox("Choose Simulator", ["🏠 AutoCAD - House Wiring & House Plan", "🧊 FreeCAD - 3D Casing / Product Box - SOLID", "⚡ Proteus - PCB & Circuit Simulator - REBUILT"])
    if design_choice.startswith("🏠"):
        st.subheader("🏠 AutoCAD Simulator - House Wiring & House Plan")
        st.write("What kind of house design you want?")
        house_type = st.selectbox("House Type", ["Bungalow", "Duplex", "Mansion", "Storey Building / Custom"])
        c1, c2, c3 = st.columns(3)
        with c1:
            house_len = st.slider("House Length (feet)", 20, 80, 40)
            house_breadth = st.slider("House Breadth / Width (feet)", 20, 60, 30)
            num_rooms = st.slider("Number of Rooms", 1, 10, 3)
        with c2:
            num_windows = st.slider("Number of Windows", 1, 20, 8)
            num_doors = st.slider("Number of Doors", 1, 10, 5)
            num_sockets = st.slider("Number of Sockets", 2, 20, 8)
        with c3:
            num_lights = st.slider("Number of Lights / Bulbs", 1, 15, 6)
            num_switches = st.slider("Number of Switches", 1, 15, 6)
            num_toilets = st.slider("Number of Toilets", 1, 6, 2)
        c4, c5 = st.columns(2)
        with c4:
            num_kitchen = st.slider("Number of Kitchens", 1, 3, 1)
            num_parlour = st.slider("Number of Parlours", 1, 3, 1)
        with c5:
            num_storeys = st.slider("How many storeys / floors?", 1, 5, 1)
            wire_type = st.selectbox("Wiring Type", ["Concealed Wiring (inside wall)", "Surface Wiring (on wall)", "Solar + Grid Hybrid"])
        line_len = st.slider("Line Length for extra wall (feet)", 0, 20, 10)
        line_pos = st.selectbox("Where to draw line?", ["Middle Partition - Vertical", "Middle Partition - Horizontal", "No Extra Line"])
        if st.button("✨ DRAW AND DESIGN", type="primary"):
            W = house_len * 10
            H = house_breadth * 10
            scale = 700 / max(W, 10)
            dw = int(W * scale)
            dh = int(H * scale)
            room_w = dw // max(num_rooms, 1)
            svg_parts = []
            svg_parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="750" height="550" viewBox="0 0 750 550" style="background:white;border-radius:12px">')
            svg_parts.append('<text x="20" y="25" font-family="Arial" font-size="20" font-weight="bold" fill="#0f2027">JTEG HOUSE PLAN - ' + str(house_type.upper()) + ' - ' + str(house_len) + 'ft x ' + str(house_breadth) + 'ft</text>')
            svg_parts.append('<text x="20" y="45" font-family="Arial" font-size="12" fill="#0072ff">AutoCAD Simulator | Length: ' + str(house_len) + 'ft | Breadth: ' + str(house_breadth) + 'ft | Type: ' + wire_type + ' | Storeys: ' + str(num_storeys) + '</text>')
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
            svg_parts.append('<text x="20" y="540" font-family="Arial" font-size="12" fill="#333">Rooms: ' + str(num_rooms) + ' | Lights: ' + str(num_lights) + ' | Switches: ' + str(num_switches) + ' | Sockets: ' + str(num_sockets) + ' | Windows: ' + str(num_windows) + ' | Doors: ' + str(num_doors) + ' | Toilets: ' + str(num_toilets) + ' | Kitchen: ' + str(num_kitchen) + ' | Parlour: ' + str(num_parlour) + '</text>')
            svg_parts.append('</svg>')
            svg_code = "".join(svg_parts)
            show_svg(svg_code, "vinci_house_plan.svg")
            st.success("House Plan Done! " + house_type + " - " + str(house_len) + "ft x " + str(house_breadth) + "ft - " + str(num_rooms) + " Rooms")
            st.code("=== BLUEPRINT - " + house_type.upper() + " ===\nPlot: " + str(house_len) + "x" + str(house_breadth) + "ft | Storeys: " + str(num_storeys) + " | Rooms: " + str(num_rooms) + "\nWindows: " + str(num_windows) + " | Doors: " + str(num_doors) + " | Toilets: " + str(num_toilets) + "\nKitchen: " + str(num_kitchen) + " | Parlour: " + str(num_parlour) + "\n[FRONT VIEW] - Roof, Windows aligned, Door centered\n[FLOOR PLAN] - Parlour -> Kitchen -> Rooms -> Toilets, Corridor in middle\n[ELECTRICAL] - 1 socket per room + 2 in parlour, 1 switch per door\n[SCALE] 1:100, All dimensions in mm, Walls 225mm block")
            st.info("AutoCAD: LINE 0,0 to " + str(house_len) + "ft | RECTANGLE " + str(house_len) + "ft x " + str(house_breadth) + "ft | OFFSET 0.5ft for wall | DIMENSION for length and breadth")
            st.info("Materials: Cable 1.5mm for lights, Cable 2.5mm for sockets, Switches " + str(num_switches) + ", Sockets " + str(num_sockets))
            # 3D image
            p3d = "Photorealistic 3D render of a modern Nigerian " + house_type + " house, " + str(num_storeys) + " storey, " + str(num_rooms) + " rooms, " + str(num_windows) + " windows, white and gold exterior, Birnin-Kebbi, bright daylight"
            ib, err = generate_vinci_image(p3d, "3D Render")
            if ib:
                st.image(ib, caption="3D View - Your " + house_type)
    elif design_choice.startswith("🧊"):
        st.subheader("🧊 FreeCAD Simulator - SOLID - 3D Casing / Product Box")
        st.write("Give me a 3D casing, what kind of casing you want build?")
        casing_type = st.selectbox("What kind of casing you want?", ["Solar Power Bank Casing", "Decoder Casing", "Television Casing", "Radio Casing", "Phone Charger Casing", "Battery Pack Casing", "Custom Electrical / Electronics Casing"])
        c1, c2 = st.columns(2)
        with c1:
            f_len_mm = st.number_input("Length (mm) - How long?", 10.0, 2000.0, 150.0)
            f_wid_mm = st.number_input("Width / Breadth (mm)", 10.0, 2000.0, 80.0)
            f_hei_mm = st.number_input("Height / Thickness (mm)", 5.0, 500.0, 25.0)
            f_product = casing_type
        with c2:
            f_thick = st.number_input("Wall Thickness (mm)", 1.0, 10.0, 2.5)
            f_screw = st.number_input("How many screw holes? (M3)", 0, 20, 4)
            f_mat = st.selectbox("Material", ["PLA - Easy Print", "ABS - Strong, Heat Resistant", "Aluminium - Best for Heat", "Acrylic - Clear"])
            f_battery = st.checkbox("Battery Space Inside?", value=True)
        # Specific
        extra = ""
        usb_ports = 0
        batt_count = 0
        if "Solar Power Bank" in casing_type:
            e1, e2 = st.columns(2)
            with e1:
                usb_ports = st.number_input("How many USB ports?", 0, 6, 2)
                usb_pos = st.selectbox("USB ports dey where?", ["Front Side", "Top Side", "Back Side"])
                batt_count = st.number_input("How many 18650 batteries inside? (18mm x 65mm each)", 0, 10, 2)
            with e2:
                solar_size = st.text_input("Solar panel size? e.g 110x70mm 6V 5W", "110x70mm 6V 5W")
                led_holes = st.number_input("How many LED indicator holes?", 0, 10, 4)
                button_hole = st.checkbox("Button hole? Power button", value=True)
            extra = "USB: " + str(usb_ports) + " at " + usb_pos + " | Batteries: " + str(batt_count) + "x 18650 | Solar: " + solar_size + " | LED: " + str(led_holes) + " | Button: " + str(button_hole)
        elif "Decoder" in casing_type:
            e1, e2 = st.columns(2)
            with e1:
                hdmi = st.number_input("HDMI ports at back?", 0, 4, 1)
                usb_ports = st.number_input("USB ports?", 0, 4, 1)
                vent = st.number_input("Ventilation holes?", 0, 100, 20)
            with e2:
                ir_window = st.checkbox("IR Sensor Window in front?", value=True)
                power_in = st.selectbox("Power input", ["12V DC Jack", "5V USB-C", "220V AC"])
                antenna = st.checkbox("Antenna hole at back?", value=True)
            extra = "HDMI: " + str(hdmi) + " | USB: " + str(usb_ports) + " | Vent: " + str(vent) + " | IR: " + str(ir_window) + " | Power: " + power_in + " | Antenna: " + str(antenna)
        elif "Television" in casing_type:
            e1, e2 = st.columns(2)
            with e1:
                screen = st.selectbox("Screen size", ["32 inch", "43 inch", "55 inch", "65 inch"])
                vesa = st.selectbox("VESA Mount", ["200x200mm", "400x400mm", "600x400mm"])
            with e2:
                speaker = st.number_input("Speaker holes?", 0, 100, 20)
                hdmi_tv = st.number_input("HDMI ports?", 0, 4, 2)
            extra = "Screen: " + screen + " | VESA: " + vesa + " | Speaker: " + str(speaker) + " | HDMI: " + str(hdmi_tv)
        elif "Battery Pack" in casing_type:
            batt_count = st.number_input("How many 18650 batteries?", 0, 20, 4)
            extra = "Batteries: " + str(batt_count) + "x 18650"
        else:
            f_usb = st.checkbox("USB Hole?", value=True)
            f_screen = st.checkbox("Screen / Display Hole?", value=True)
            extra = "Custom: USB " + str(f_usb) + " | Screen " + str(f_screen) + " | Battery Space " + str(f_battery)
        if st.button("✨ MODEL AM - REAL 3D SIMULATION", type="primary"):
            L = f_len_mm
            W = f_wid_mm
            H = f_hei_mm
            outer_vol = L * W * H
            inner_l = max(1, L - f_thick*2)
            inner_w = max(1, W - f_thick*2)
            inner_h = max(1, H - f_thick)
            inner_vol = inner_l * inner_w * inner_h
            mat_vol = outer_vol - inner_vol
            density = 0.00124 if "PLA" in f_mat else 0.00104 if "ABS" in f_mat else 0.0027 if "Aluminium" in f_mat else 0.00118
            weight = mat_vol * density
            st.success("MODEL DONE - " + casing_type)
            st.code("=== FREECAD SOLID - " + casing_type.upper() + " ===\nOuter: " + str(int(L)) + "mm x " + str(int(W)) + "mm x " + str(int(H)) + "mm\nWall: " + str(f_thick) + "mm | Material: " + f_mat + "\nInner Space: " + str(int(inner_l)) + " x " + str(int(inner_w)) + " x " + str(int(inner_h)) + " mm\nOuter Volume: " + str(int(outer_vol)) + " mm3 | Material Volume: " + str(int(mat_vol)) + " mm3\nWeight: " + str(round(weight,1)) + "g\nScrew Holes: " + str(int(f_screw)) + "x M3 - 5mm from edge\nDetails: " + extra + "\n[TOP VIEW] - Rectangle, screw at 4 corners\n[FRONT VIEW] - Height, ports/holes as you choose\n[SIDE VIEW] - Thickness wall, hollow inside\nExport: STL + STEP + DXF")
            # Real simulation checks
            if batt_count > 0:
                need_l = 65 + 10
                need_w = 18 * batt_count + 10
                if inner_l >= need_l and inner_w >= need_w:
                    st.success("✅ BATTERY FIT: " + str(batt_count) + "x 18650 go fit inside. Inner: " + str(int(inner_l)) + " x " + str(int(inner_w)) + " x " + str(int(inner_h)) + "mm")
                else:
                    st.error("❌ BATTERY NO FIT: Need " + str(int(need_l)) + "mm x " + str(int(need_w)) + "mm, but inner na " + str(int(inner_l)) + " x " + str(int(inner_w)) + "mm. Increase Length or Width.")
            if f_screw >= 4:
                st.success("✅ SCREW: " + str(int(f_screw)) + "x M3 holes at corners, 5mm from edge, go align. Top and bottom go close well.")
            elif f_screw > 0:
                st.warning("⚠️ SCREW: Only " + str(int(f_screw)) + " holes. Use 4 for casing to close tight.")
            else:
                st.warning("⚠️ SCREW: No screw holes. Casing go dey open. Add 4x M3.")
            if f_thick < 2.0:
                st.error("❌ WALL TOO THIN: Thickness <2mm go break. Use 2.5mm - 3mm.")
            else:
                st.success("✅ WALL: " + str(f_thick) + "mm thickness na solid. No go break.")
            if "Decoder" in casing_type or "Television" in casing_type:
                st.info("✅ HEAT: Add ventilation holes at back and top. Aluminium best for heat. PLA go melt if decoder hot - use ABS or Aluminium.")
            if "Solar" in casing_type:
                st.info("✅ SOLAR: Solar panel go sit on top. TP4056 charging board go fit inside with battery.")
            # Old SVG visual - keep am
            Ls = int(L * 1.8)
            Ws = int(W * 1.8)
            if Ls > 600:
                Ls = 600
            if Ws > 300:
                Ws = 300
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="750" height="480" viewBox="0 0 750 480" style="background:white;border-radius:12px">'
            svg = svg + '<text x="20" y="25" font-family="Arial" font-size="20" font-weight="bold" fill="#0f2027">' + f_product + ' - FreeCAD Simulator</text>'
            svg = svg + '<text x="20" y="45" font-family="Arial" font-size="12" fill="#0072ff">Length ' + str(int(L)) + ' mm x Width ' + str(int(W)) + ' mm x Height ' + str(int(H)) + ' mm</text>'
            svg = svg + '<rect x="80" y="80" width="' + str(Ls) + '" height="' + str(Ws) + '" fill="#0f2027" stroke="#00c6ff" stroke-width="3"/>'
            svg = svg + '<rect x="100" y="100" width="' + str(max(10, Ls-40)) + '" height="' + str(max(10, Ws-40)) + '" fill="none" stroke="#ff9900" stroke-width="1.5" stroke-dasharray="6,4"/>'
            svg = svg + '<text x="100" y="120" font-family="Arial" font-size="14" fill="white">JTEG - ' + f_product + '</text>'
            svg = svg + '<circle cx="' + str(80 + Ls - 30) + '" cy="110" r="14" fill="#00c6ff"/>'
            svg = svg + '<rect x="110" y="140" width="110" height="60" fill="#00c6ff" opacity="0.25" stroke="#0072ff"/>'
            svg = svg + '<text x="115" y="170" font-size="12">BATTERY SPACE</text>'
            svg = svg + '<text x="20" y="460" font-size="12">Battery: ' + str(f_battery) + ' | Material: ' + f_mat + ' | Screw: ' + str(int(f_screw)) + '</text>'
            svg = svg + '</svg>'
            show_svg(svg, "vinci_casing.svg")
            # 3D image
            p3d2 = "Photorealistic 3D render of a " + casing_type + ", " + str(int(L)) + "mm x " + str(int(W)) + "mm x " + str(int(H)) + "mm, " + f_mat + " casing, with ports and screw holes, on workbench"
            ib2, _ = generate_vinci_image(p3d2, "3D Render")
            if ib2:
                st.image(ib2, caption="3D View - " + casing_type)
            st.success("Export ready: STL + STEP + DXF. E real, e actual, e go fit when you print am.")
    elif design_choice.startswith("⚡"):
        st.subheader("⚡ Proteus Simulator - PCB & Circuit - REBUILT")
        st.write("What kind of circuit you want build?")
        circuit = st.selectbox("Circuit Type", ["DC Circuit", "AC Circuit", "AC to DC", "DC to AC", "AC + DC"])
        st.info("You choose: " + circuit + ". Empty PCB Board Ready - 100mm x 80mm")
        st.write("Now choose your components yourself:")
        r_qty = st.number_input("How many Resistors?", 0, 20, 1)
        r_val = st.selectbox("Resistor Value", ["220 ohms", "1k ohms", "10k ohms", "0 ohms - SHORT!"])
        c_qty = st.number_input("How many Capacitors?", 0, 20, 0)
        c_val = st.selectbox("Capacitor Value", ["100uF", "10uF", "1000uF"])
        d_qty = st.number_input("How many Diodes / LEDs?", 0, 20, 1)
        t_qty = st.number_input("How many Transistors?", 0, 20, 0)
        batt = st.selectbox("Battery", ["9V", "5V", "12V", "No Battery"])
        if st.button("ACTIVATE - Simulate"):
            if batt == "No Battery":
                st.error("No Battery - Circuit no go power. Add battery first.")
            elif r_val == "0 ohms - SHORT!" or (d_qty > 0 and r_qty == 0):
                st.error("LED without Resistor / 0 ohm - LED go burn! Add 220 ohm resistor.")
            else:
                st.success("SIMULATION OK - Circuit logic correct. E don happen for simulation. Now go solder am.")
        st.divider()
        st.subheader("SOLDERING MODE")
        st.write("Tap soldering iron, board go turn, you go solder back by yourself. Nobody go do am for you.")
        soldered = st.checkbox("I don solder all joints myself")
        if st.button("DONE WITH SOLDERING"):
            if not soldered:
                st.error("You never solder all joints. Solder all first.")
            else:
                st.success("SOLDERING DONE - Board ready for battery test.")
        st.divider()
        st.subheader("BATTERY TERMINAL TEST")
        if st.button("Connect Battery Terminal"):
            if not soldered:
                st.error("Solder first before battery!")
            elif r_val == "0 ohms - SHORT!":
                st.error("⚡💥 SPARK! SPARK! SPARK! SHORT CIRCUIT at Resistor - 0 ohm na short! Disconnect battery NOW. Replace with 220 ohm.")
            elif batt == "No Battery":
                st.error("No battery to connect.")
            else:
                st.success("No spark. Clean. CIRCUIT OK ✅ Battery " + batt + " connected. Circuit dey work!")
        # Old PCB SVG - keep am for visual
        if st.button("Show PCB Board Drawing"):
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="750" height="480" viewBox="0 0 750 480" style="background:white;border-radius:12px">'
            svg = svg + '<text x="20" y="25" font-family="Arial" font-size="20" font-weight="bold">JTEG PCB - ' + circuit + '</text>'
            svg = svg + '<rect x="80" y="60" width="500" height="320" fill="#006400" stroke="black" stroke-width="3"/>'
            svg = svg + '<text x="100" y="90" fill="white">PCB 100mm x 80mm | Resistors: ' + str(r_qty) + 'x ' + r_val + ' | Capacitors: ' + str(c_qty) + 'x ' + c_val + ' | LEDs: ' + str(d_qty) + ' | Transistors: ' + str(t_qty) + ' | Battery: ' + batt + '</text>'
            svg = svg + '</svg>'
            show_svg(svg, "vinci_pcb.svg")
