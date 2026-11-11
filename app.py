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

# ===== VOICE - CLEAN, NO TAGS =====
def clean_for_voice(text):
    t = text.replace("*","").replace("#","").replace("_","").replace("`","").replace("<","").replace(">","").replace("/"," ").replace("\\"," ")
    t = re.sub(r'http\S+','',t)
    t = re.sub(r'\s+',' ',t).strip()
    return t[:900]

async def speak_human(text):
    clean = clean_for_voice(text)
    if not clean: return None
    for voice in ["en-NG-AbeoNeural", "en-US-GuyNeural"]:
        try:
            communicate = edge_tts.Communicate(clean, voice, rate="+10%", pitch="+2Hz")
            mp3_fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"]=="audio": mp3_fp.write(chunk["data"])
            mp3_fp.seek(0)
            return mp3_fp.getvalue()
        except Exception: continue
    return None

def speak(text):
    try:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        b = loop.run_until_complete(speak_human(text)); loop.close(); return b
    except Exception: return None

def ask_vinci(prompt, image=None, mode="chat"):
    proj = "\n".join([f"- {p['title']} ({p['status']}): {p['desc']}" for p in st.session_state.projects])
    rem = "\n".join([f"- {r['date']} {r['time']}: {r['text']}" for r in st.session_state.reminders])
    expert = f"""
You are Vinci AI, Jarvis for JTEG. Say JTEG as one word Jay-Teg. Never spell J-T-E-G.
User is Josiah, Electrical Engineer in Birnin-Kebbi, CEO of JTEG. We go earn am together.
Speak human, MEDIUM speed. Short sentences. Comma for small pause, full stop for big pause. Question mark for rising voice. No symbols like star hash slash in answer. Plain words only.
Master of AutoCAD, FreeCAD, Proteus. When user asks design, give Dimensions, Materials, AutoCAD steps, FreeCAD steps, Proteus steps, How to build.
Keep LIVE answers short 3-4 sentences unless user asks full design.
Projects: {proj if proj else 'None'}
Reminders: {rem if rem else 'None'}
Mode: {mode}
User: {prompt}
"""
    if image:
        img = Image.open(image)
        resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=[expert, img])
    else:
        resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=expert)
    return resp.text

# ===== IMAGE - POLLINATIONS FREE, NO API KEY, NO QUOTA, NO 429 =====
def generate_vinci_image(prompt_text, style="Product Design"):
    try:
        full = f"{style}, {prompt_text}, high quality, detailed, professional JTEG design, clean background"
        encoded = urllib.parse.quote(full)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&seed=42&nologo=true&model=flux"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            img_bytes = resp.read()
        if len(img_bytes) > 1000:
            return img_bytes, None
        else:
            return None, "Image engine busy, try again in 5 seconds."
    except Exception as e:
        return None, f"Image engine busy: {e}. Try again, or use Design Studio - that one never fails."

# ===== DESIGN STUDIO HELPERS =====
def show_svg(svg_code, filename="vinci_design.svg"):
    b64 = base64.b64encode(svg_code.encode()).decode()
    st.markdown(f'<img src="data:image/svg+xml;base64,{b64}" style="width:100%;background:white;border-radius:12px;padding:5px;">', unsafe_allow_html=True)
    st.download_button("Download Drawing (SVG)", data=svg_code, file_name=filename, mime="image/svg+xml")

if "messages" not in st.session_state: st.session_state.messages=[]
if "projects" not in st.session_state: st.session_state.projects=[]
if "reminders" not in st.session_state: st.session_state.reminders=[]
if "gen_images" not in st.session_state: st.session_state.gen_images=[]
if "live_on" not in st.session_state: st.session_state.live_on=False

with st.sidebar:
    st.header("📁 My Projects - JTEG")
    proj_title = st.text_input("Project Name", placeholder="e.g. Smart Solar Charger")
    proj_desc = st.text_area("Project Details")
    proj_status = st.selectbox("Status", ["Idea 💡","In Progress 🔨","Done ✅","Paused ⏸️"])
    if st.button("Save Project"):
        if proj_title:
            st.session_state.projects.append({"title":proj_title,"desc":proj_desc,"status":proj_status,"date":str(date.today())}); st.success("Saved"); st.rerun()
    for i,p in enumerate(st.session_state.projects):
        with st.expander(f"{p['status']} - {p['title']}"):
            st.write(p['desc'])
            if st.button("Delete", key=f"delp{i}"): st.session_state.projects.pop(i); st.rerun()
    st.divider(); st.header("⏰ Reminders")
    rem_text = st.text_input("Reminder"); rem_date = st.date_input("Date", value=date.today()); rem_time = st.time_input("Time", value=time(8,0))
    if st.button("Set Reminder"):
        if rem_text: st.session_state.reminders.append({"text":rem_text,"date":str(rem_date),"time":str(rem_time)}); st.rerun()
    for i,r in enumerate(st.session_state.reminders):
        st.info(f"⏰ {r['date']} {r['time']} - {r['text']}")
        if st.button("Done", key=f"delr{i}"): st.session_state.reminders.pop(i); st.rerun()

# ===== TABS =====
tab_chat, tab_live, tab_image, tab_design, tab_video = st.tabs(["💬 1. CHAT", "🔴 2. LIVE", "🎨 3. IMAGE", "📐 4. DESIGN STUDIO - AutoCAD + FreeCAD + Proteus", "🎬 5. VIDEO"])

# ===== 1. CHAT =====
with tab_chat:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            if msg.get("audio"): st.audio(msg["audio"])
    st.markdown("### Type or Talk - side by side")
    col_t, col_m = st.columns([4,1])
    with col_t:
        text_prompt = st.chat_input("Type your message here... Ask Vinci anything...")
    with col_m:
        st.caption("🎤 Voice")
        audio = st.audio_input("Tap mic", key="chat_mic")
    prompt=None
    img_chat = st.file_uploader("📷 Upload image (optional)", type=["jpg","jpeg","png","webp"], key="chat_up")
    if img_chat: st.image(img_chat, width=300)
    if audio:
        try:
            r=sr.Recognizer(); b=audio.read()
            open("temp.wav","wb").write(b)
            with sr.AudioFile("temp.wav") as src: ad=r.record(src); prompt=r.recognize_google(ad); st.success(f"You said: {prompt}")
        except Exception as e: st.error(f"Could not hear: {e}")
    if text_prompt: prompt=text_prompt
    if prompt or (img_chat and st.button("Ask Vinci about this image")):
        if not prompt: prompt="Explain this image in detail, like Jarvis. If circuit/design, give parts, dimensions, how to build/improve."
        st.session_state.messages.append({"role":"user","text":prompt})
        with st.chat_message("assistant"):
            try:
                answer=ask_vinci(prompt, img_chat, "CHAT")
                st.markdown(answer)
                ab=speak(answer)
                if ab: st.audio(ab, format="audio/mp3"); st.session_state.messages.append({"role":"assistant","text":answer,"audio":ab})
                else: st.session_state.messages.append({"role":"assistant","text":answer})
            except Exception as e: st.error(f"Error: {e}")

# ===== 2. LIVE - MASTER SWITCH =====
with tab_live:
    st.header("🔴 LIVE - Real Jarvis Mode")
    live_on = st.toggle("🔴 LIVE MASTER SWITCH - ON / OFF", value=st.session_state.get("live_on", False), key="live_master_toggle")
    st.session_state.live_on = live_on
    if not live_on:
        st.warning("⏹️ LIVE IS OFF - Vinci is quiet now. E no dey listen. Turn switch ON when you want am again.")
    else:
        st.success("🟢 LIVE IS ON - Vinci dey listen for 'Vinci...'")
        st.caption("To turn OFF: Flip MASTER SWITCH above to OFF. Vinci go stop immediately.")
        live_html = """
<div style="background:#12233f;padding:18px;border-radius:15px;color:white;font-family:Arial">
  <h3 style="color:white">🔴 LIVE ENGINE - ALWAYS LISTENING</h3>
  <p id="liveStatus" style="color:#ffcc00;font-weight:bold">● Click START LIVE to turn mic ON</p>
  <p id="liveHeard" style="background:rgba(255,255,255,0.1);padding:10px;border-radius:10px;min-height:60px">Waiting for 'Vinci...' - say: Vinci, who am I?</p>
  <p id="liveAnswer" style="background:rgba(0,198,255,0.15);padding:10px;border-radius:10px;min-height:60px">Vinci answer go appear here.</p>
  <button onclick="startLive()" style="background:#00c6ff;color:white;border:none;padding:12px 20px;border-radius:20px;font-weight:bold;cursor:pointer">▶ START LIVE</button>
  <button onclick="stopLive()" style="background:#ff4444;color:white;border:none;padding:12px 20px;border-radius:20px;font-weight:bold;cursor:pointer;margin-left:10px">⏹ STOP LIVE</button>
</div>
<script>
let rec=null, listening=false, silenceTimer=null;
let synth = window.speechSynthesis;
function speakLive(text){ if(synth.speaking) synth.cancel(); let u = new SpeechSynthesisUtterance(text); u.rate=1.0; u.pitch=1.0; u.lang='en-NG'; synth.speak(u); }
function startLive(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){ document.getElementById('liveStatus').innerText='Browser no support Live. Use Chrome.'; return; }
  if(listening) return; listening=true;
  document.getElementById('liveStatus').innerText='🟢 LIVE ON - Mic always ON - Say Vinci...';
  document.getElementById('liveStatus').style.color='#00ff88';
  rec = new SR(); rec.continuous=true; rec.interimResults=true; rec.lang='en-NG';
  rec.onresult = (e)=>{
    let interim=""; for(let i=e.resultIndex;i<e.results.length;i++){ interim+=e.results[i][0].transcript; }
    if(synth.speaking && interim.trim().length>2){ synth.cancel(); }
    document.getElementById('liveHeard').innerText='Hearing: '+interim;
    clearTimeout(silenceTimer);
    silenceTimer=setTimeout(()=>{
      let t=interim.toLowerCase();
      if(t.includes('vinci')){
        let ans="Yes boss, I hear you. "+interim+". I go do am sharp sharp.";
        if(t.includes('who am i')) ans="Boss, you are Josiah, CEO of JTEG, Josiah Technology and Engineering Limited. We go earn am together.";
        if(t.includes('12 inch')||t.includes('solar')) ans="Yes boss, 12 inch solar charger casing. Length 12 inch, width 8 inch, height 2 inch. Go to Design Studio tab.";
        document.getElementById('liveAnswer').innerText='Vinci: '+ans; speakLive(ans);
      } else if(interim.trim().length>3){ document.getElementById('liveHeard').innerText='I hear you, but call me Vinci first. Say: Vinci, do this.'; }
    }, 1500);
  };
  rec.onend=()=>{ if(listening) rec.start(); };
  rec.onerror=(e)=>{ document.getElementById('liveStatus').innerText='Mic error: '+e.error+' - Click START again and allow mic.'; };
  rec.start();
}
function stopLive(){ listening=false; if(rec){ try{ rec.stop(); }catch(e){} rec=null; } if(synth.speaking) synth.cancel(); clearTimeout(silenceTimer); document.getElementById('liveStatus').innerText='⏹ LIVE STOPPED - Mic OFF'; document.getElementById('liveStatus').style.color='#ff4444'; }
</script>
"""
        components.html(live_html, height=420)
        st.divider()
        st.subheader("LIVE with Gemini Brain (Backup)")
        live_audio2 = st.audio_input("Backup - tap and talk", key="live_backup")
        if live_audio2:
            try:
                r=sr.Recognizer(); b=live_audio2.read(); open("temp2.wav","wb").write(b)
                with sr.AudioFile("temp2.wav") as src: ad=r.record(src); lp=r.recognize_google(ad); st.success(f"You said: {lp}")
                ans=ask_vinci(lp, None, "LIVE - SHORT")
                st.markdown(ans); ab=speak(ans)
                if ab: st.audio(ab, format="audio/mp3", autoplay=True)
            except Exception as e: st.error(str(e))

# ===== 3. IMAGE - POLLINATIONS =====
with tab_image:
    st.header("🎨 IMAGE - Pollinations Free, No Quota, No Payment")
    st.caption("Chat still uses Gemini 3.5 Flash-Lite. Image uses Pollinations Flux - free unlimited.")
    img_prompt = st.text_area("Describe image", placeholder="e.g. JTEG solar power bank, black and blue, Blue")
    img_style = st.selectbox("Style", ["Product Design","Realistic Photo","Circuit Diagram","3D Render","Blueprint / Technical Drawing","Logo"])
    if st.button("🎨 Generate Image", type="primary"):
        if img_prompt:
            with st.spinner("Vinci is drawing am with Pollinations..."):
                img_bytes, err = generate_vinci_image(img_prompt, img_style)
                if img_bytes:
                    st.image(img_bytes, caption=img_prompt, use_container_width=True)
                    st.download_button("Download", data=img_bytes, file_name="vinci_jteg.png", mime="image/png")
                    st.session_state.gen_images.append(img_bytes)
                else: st.warning(err)
        else: st.warning("Type first")
    st.divider()
    for idx, ib in enumerate(st.session_state.gen_images):
        st.image(ib, width=300)

# ===== 4. DESIGN STUDIO - AUTOCAD + FREECAD + PROTEUS SIMULATORS =====
with tab_design:
    st.header("📐 DESIGN STUDIO - Your AutoCAD + FreeCAD + Proteus Inside Vinci")
    st.write("No need install AutoCAD. No need install FreeCAD. No need install Proteus. Everything dey here. You draw, you arrange, you simulate.")
    design_choice = st.selectbox("Choose Simulator", ["🏠 AutoCAD - House Wiring & House Plan", "🧊 FreeCAD - 3D Casing / Product Box", "⚡ Proteus - PCB & Circuit Simulator"])

    # ----- AUTOCAD - HOUSE WIRING -----
    if design_choice.startswith("🏠"):
        st.subheader("🏠 AutoCAD Simulator - House Wiring & House Plan")
        st.caption("Put length, breadth, arrange house, windows, doors, sockets. Vinci go draw house plan like AutoCAD.")
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
        # Extra: draw line tool
        st.markdown("**✏️ Draw Line Tool - Like AutoCAD LINE command**")
        line_len = st.slider("Line Length for extra wall / partition (feet)", 0, 20, 10)
        line_pos = st.selectbox("Where to draw line?", ["Middle Partition - Vertical", "Middle Partition - Horizontal", "Kitchen Partition", "No Extra Line"])
        if st.button("✨ Draw House Plan Now", type="primary"):
            # Build SVG house plan - scale: 1 foot = 10px
            W = house_len * 10
            H = house_breadth * 10
            # Cap for display
            scale = 700 / max(W, 10)
            dw = int(W * scale)
            dh = int(H * scale)
            # Rooms partitions
            room_w = dw // max(num_rooms, 1)
            svg_parts = []
            svg_parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="750" height="550" viewBox="0 0 750 550" style="background:white;border-radius:12px">')
            svg_parts.append(f'<text x="20" y="25" font-family="Arial" font-size="20" font-weight="bold" fill="#0f2027">JTEG HOUSE PLAN - {house_len}ft x {house_breadth}ft - {wire_type}</text>')
            svg_parts.append(f'<text x="20" y="45" font-family="Arial" font-size="12" fill="#0072ff">AutoCAD Simulator | Scale 1ft = {scale:.1f}px | Length: {house_len}ft ({house_len*304.8:.0f}mm) | Breadth: {house_breadth}ft ({house_breadth*304.8:.0f}mm)</text>')
            # Outer wall
            svg_parts.append(f'<rect x="30" y="60" width="{dw}" height="{dh}" fill="#f5f5f5" stroke="black" stroke-width="4"/>')
            # Rooms
            for i in range(num_rooms):
                x = 30 + i * room_w
                svg_parts.append(f'<rect x="{x}" y="60" width="{room_w}" height="{dh}" fill="none" stroke="#333" stroke-width="2"/>')
                svg_parts.append(f'<text x="{x+10}" y="80" font-family="Arial" font-size="12" font-weight="bold">ROOM {i+1}</text>')
                # Light in each room
                svg_parts.append(f'<circle cx="{x+room_w//2}" cy="{60+dh//2-20}" r="10" fill="yellow" stroke="black"/><text x="{x+room_w//2-4}" y="{60+dh//2-16}" font-size="10">💡</text>')
                # Socket
                svg_parts.append(f'<rect x="{x+10}" y="{60+dh-30}" width="14" height="10" fill="white" stroke="red"/><text x="{x+10}" y="{60+dh-35}" font-size="8" fill="red">SOCKET</text>')
            # Windows - blue marks on top wall
            for i in range(num_windows):
                wx = 50 + i * (dw // max(num_windows,1))
                svg_parts.append(f'<rect x="{wx}" y="56" width="30" height="8" fill="#00c6ff" stroke="blue"/><text x="{wx}" y="52" font-size="8" fill="blue">WIN</text>')
            # Doors - brown marks on bottom wall
            for i in range(num_doors):
                dx = 60 + i * (dw // max(num_doors,1))
                svg_parts.append(f'<rect x="{dx}" y="{60+dh-2}" width="35" height="8" fill="#8B4513"/><text x="{dx}" y="{60+dh+18}" font-size="8" fill="brown">DOOR</text>')
            # Extra line
            if line_pos != "No Extra Line":
                if "Vertical" in line_pos:
                    svg_parts.append(f'<line x1="{30+dw//2}" y1="60" x2="{30+dw//2}" y2="{60+dh}" stroke="red" stroke-width="2" strok
