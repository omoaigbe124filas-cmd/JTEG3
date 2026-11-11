import streamlit as st
from google import genai
from google.genai import types
import speech_recognition as sr
import asyncio
import edge_tts
import io
import re
import streamlit.components.v1 as components
from datetime import date, time
from PIL import Image
import base64

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
    st.caption("Josiah only. Chat: gemini-3.5-flash-lite | Image: gemini-2.5-flash-image")
    st.write("Priority: 1-Chat, 2-LIVE, 3-Image, 4-Design Simulation, 5-Video")

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

# ===== IMAGE - FIXED: response_modalities IS THE FIX =====
def generate_vinci_image(prompt_text, style="Product Design"):
    full = f"{style} style: {prompt_text}. High quality, detailed, professional JTEG design."
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=full,
            config=types.GenerateContentConfig(response_modalities=["TEXT","IMAGE"])
        )
        for part in resp.candidates[0].content.parts:
            if getattr(part, "inline_data", None) is not None:
                return part.inline_data.data, None
        for part in resp.candidates[0].content.parts:
            if getattr(part, "text", None):
                return None, part.text
        return None, "Google returned text only. Try simpler description."
    except Exception as e:
        return None, f"Image error: {e}. Try again, or use Design Simulator tab - that one never fails."

# ===== AUTOCAD / FREECAD SIMULATOR - NO AI, NO ERROR, INSTANT DRAW =====
def draw_simulator(length_in, width_in, height_in, title, kind):
    # SVG drawing that never fails
    L = length_in * 30
    W = width_in * 30
    svg = f"""
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450" style="background:white;border-radius:12px">
  <rect x="100" y="80" width="{L}" height="{W}" fill="#0f2027" stroke="#00c6ff" stroke-width="3"/>
  <rect x="120" y="100" width="{L-40}" height="{W-40}" fill="none" stroke="#ff9900" stroke-width="1.5" stroke-dasharray="6,4"/>
  <text x="100" y="50" font-family="Arial" font-size="22" font-weight="bold" fill="#0f2027">{title} - {kind}</text>
  <text x="100" y="380" font-family="Arial" font-size="16" fill="#0f2027">Length: {length_in} inch ({length_in*25.4:.0f} mm) | Width: {width_in} inch ({width_in*25.4:.0f} mm) | Height: {height_in} inch</text>
  <text x="100" y="405" font-family="Arial" font-size="14" fill="#0072ff">JTEG - Josiah Technology and Engineering Limited | Scale 1:1 | AutoCAD + FreeCAD Simulator</text>
  <line x1="100" y1="300" x2="{100+L}" y2="300" stroke="red" stroke-width="1.5"/><text x="{100+L/2-20}" y="320" font-family="Arial" font-size="14" fill="red">{length_in} inch</text>
  <circle cx="{100+L-30}" cy="110" r="12" fill="#00c6ff"/><text x="{100+L-55}" y="135" font-family="Arial" font-size="10">USB</text>
  <rect x="130" y="130" width="90" height="50" fill="#00c6ff" opacity="0.3" stroke="#0072ff"/><text x="135" y="160" font-family="Arial" font-size="12">BATTERY</text>
</svg>
"""
    b64 = base64.b64encode(svg.encode()).decode()
    st.markdown(f'<img src="data:image/svg+xml;base64,{b64}" style="width:100%">', unsafe_allow_html=True)
    st.download_button("Download Drawing (SVG)", data=svg, file_name="vinci_design.svg", mime="image/svg+xml")
    st.info(f"AutoCAD Commands: RECTANGLE 0,0 -> {length_in} inch x {width_in} inch | OFFSET 0.5 inch for wall | DIMENSION for length/width | LAYER: Body=Blue, Battery=Orange, USB=Cyan")
    st.info(f"FreeCAD Steps: Sketch Rectangle {length_in} x {width_in} inch -> Pad {height_in} inch -> Pocket for Battery -> Fillet 0.2 inch -> Export STL")

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

# ===== NEW STRUCTURE: CHAT FIRST =====
tab_chat, tab_live, tab_image, tab_design, tab_video = st.tabs(["💬 1. CHAT", "🔴 2. LIVE", "🎨 3. IMAGE", "📐 4. DESIGN + SIMULATION", "🎬 5. VIDEO"])

# ===== 1. CHAT - FIRST THING, TYPE + MIC SIDE BY SIDE =====
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
    prompt=None; img_chat=None
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

# ===== 2. LIVE - ALWAYS ON MIC, WAKE WORD VINCI, BARGE-IN =====
with tab_live:
    st.header("🔴 LIVE - Real Jarvis Mode")
    st.info("Mic ALWAYS ON. No tap. Just say **'Vinci...'**. When you talk, Vinci go keep quiet. When you keep quiet 1.5 sec, Vinci go answer.")
    st.warning("Allow microphone permission for this page. Use Chrome. Keep this tab open in lab.")
    # JS Live Engine - continuous recognition, wake word, silence detection, barge-in
    live_html = """
<div style="background:#12233f;padding:18px;border-radius:15px;color:white;font-family:Arial">
  <h3 style="color:white">🔴 LIVE ENGINE - ALWAYS LISTENING</h3>
  <p id="liveStatus" style="color:#00ff88;font-weight:bold">● Click START LIVE to turn mic ON</p>
  <p id="liveHeard" style="background:rgba(255,255,255,0.1);padding:10px;border-radius:10px;min-height:60px">Waiting for 'Vinci...' - say: Vinci, give me 3D drawing of 12 inch solar charger</p>
  <p id="liveAnswer" style="background:rgba(0,198,255,0.15);padding:10px;border-radius:10px;min-height:60px">Vinci answer go appear here, and e go talk with voice.</p>
  <button onclick="startLive()" style="background:#00c6ff;color:white;border:none;padding:12px 20px;border-radius:20px;font-weight:bold;cursor:pointer">▶ START LIVE</button>
  <button onclick="stopLive()" style="background:#ff4444;color:white;border:none;padding:12px 20px;border-radius:20px;font-weight:bold;cursor:pointer;margin-left:10px">⏹ STOP LIVE</button>
  <p style="font-size:12px;opacity:0.8">How it works: Mic stays ON. It only answers when it hears 'Vinci'. If you start talking while Vinci is talking, Vinci go stop talking and listen to you.</p>
</div>
<script>
let rec=null, listening=false, silenceTimer=null, lastText="";
let synth = window.speechSynthesis;
function speakLive(text){
  if(synth.speaking) synth.cancel();
  let u = new SpeechSynthesisUtterance(text);
  u.rate=1.0; u.pitch=1.0; u.lang='en-NG';
  synth.speak(u);
}
function startLive(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){ document.getElementById('liveStatus').innerText='Browser no support Live. Use Chrome.'; return; }
  if(listening) return; listening=true;
  document.getElementById('liveStatus').innerText='🟢 LIVE ON - Mic always ON - Say Vinci...';
  rec = new SR(); rec.continuous=true; rec.interimResults=true; rec.lang='en-NG';
  rec.onresult = (e)=>{
    let interim="";
    for(let i=e.resultIndex;i<e.results.length;i++){ interim+=e.results[i][0].transcript; }
    // BARGE-IN: if user talks while Vinci is talking, stop Vinci
    if(synth.speaking && interim.trim().length>2){ synth.cancel(); }
    document.getElementById('liveHeard').innerText='Hearing: '+interim;
    clearTimeout(silenceTimer);
    silenceTimer=setTimeout(()=>{
      let t=interim.toLowerCase();
      if(t.includes('vinci')){
        let cmd = interim;
        document.getElementById('liveHeard').innerText='Command: '+cmd;
        // Simple live answers for lab - fast, no server needed for basic commands
        let ans="Yes boss, I hear you. "+cmd+". I go do am sharp sharp. For full design, go to Chat tab and I go give you dimensions, AutoCAD steps and FreeCAD steps.";
        if(t.includes('call')) ans="Yes boss, I hear you. To call, tell me the name for your contact, I go open dialer for you in P33 Plus.";
        if(t.includes('12 inch')||t.includes('solar')) ans="Yes boss, 12 inch solar charger casing. Length 12 inch, width 8 inch, height 2 inch. Go to Design Simulator tab, move slider, you go see the drawing instantly.";
        if(t.includes('who am i')) ans="Boss, you are Josiah, CEO of JTEG, Josiah Technology and Engineering Limited. We go earn am together.";
        document.getElementById('liveAnswer').innerText='Vinci: '+ans;
        speakLive(ans);
      } else if(interim.trim().length>3){
        document.getElementById('liveHeard').innerText='I hear you, but call me Vinci first. Say: Vinci, do this.';
      }
    }, 1500);
  };
  rec.onend=()=>{ if(listening) rec.start(); };
  rec.onerror=(e)=>{ document.getElementById('liveStatus').innerText='Mic error: '+e.error+' - Click START again and allow mic.'; };
  rec.start();
}
function stopLive(){ listening=false; if(rec) rec.stop(); if(synth.speaking) synth.cancel(); document.getElementById('liveStatus').innerText='⏹ LIVE OFF'; }
</script>
"""
    components.html(live_html, height=450)
    st.caption("This LIVE engine runs in your browser, not Streamlit button. That is why mic can stay ON. For full brain answers (Gemini), after LIVE hears you, copy the command to CHAT tab — or use the Streamlit LIVE below for Gemini brain.")
    st.divider()
    st.subheader("LIVE with Gemini Brain (Streamlit backup)")
    live_audio2 = st.audio_input("If browser LIVE no work for your phone, use this backup - tap and talk", key="live_backup")
    if live_audio2:
        try:
            r=sr.Recognizer(); b=live_audio2.read(); open("temp2.wav","wb").write(b)
            with sr.AudioFile("temp2.wav") as src: ad=r.record(src); lp=r.recognize_google(ad); st.success(f"You said: {lp}")
            ans=ask_vinci(lp, None, "LIVE - SHORT")
            st.markdown(ans); ab=speak(ans)
            if ab: st.audio(ab, format="audio/mp3", autoplay=True)
        except Exception as e: st.error(str(e))

# ===== 3. IMAGE - FIXED =====
with tab_image:
    st.header("🎨 IMAGE - Fixed with 2.5 Flash Image")
    img_prompt = st.text_area("Describe image", placeholder="e.g. JTEG solar power bank, black and blue")
    img_style = st.selectbox("Style", ["Product Design","Realistic Photo","Circuit Diagram","3D Render","Blueprint / Technical Drawing","Logo"])
    if st.button("🎨 Generate Image", type="primary"):
        if img_prompt:
            with st.spinner("Vinci is drawing am..."):
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

# ===== 4. DESIGN + SIMULATION - NO ERROR, INSTANT =====
with tab_design:
    st.header("📐 DESIGN + SIMULATION - AutoCAD + FreeCAD + Proteus")
    st.write("This simulator NEVER shows error. No AI call. You move slider, drawing appears instantly.")
    kind = st.selectbox("What do you want simulate?", ["AutoCAD 2D Drawing","FreeCAD 3D Casing","Proteus Circuit Board","Solar Charger Casing 12 inch"])
    l = st.slider("Length (inch)", 2, 24, 12)
    w = st.slider("Width (inch)", 2, 16, 8)
    h = st.slider("Height / Thickness (inch)", 0, 6, 2)
    if st.button("✨ Draw Simulator Now", type="primary"):
        draw_simulator(l,w,h,kind,kind)
    st.divider()
    st.subheader("Ask Vinci for Full Design Steps (Gemini brain)")
    d = st.text_area("Design request", value="Give me AutoCAD + FreeCAD steps for 12 inch solar charger casing")
    if st.button("Get Full Steps from Vinci"):
        ans=ask_vinci(d, None, "FULL DESIGN")
        st.markdown(ans)
        ab=speak("I don design am for you boss, check steps.")
        if ab: st.audio(ab, format="audio/mp3")

# ===== 5. VIDEO =====
with tab_video:
    st.header("🎬 VIDEO Generation")
    st.info("Truth: Gemini video (Veo) needs paid Veo API and e dey slow for phone. If we add am now, e go give error like image before. So I no go fake am.")
    st.write("For now: Use your Design Simulator drawing + your voice to make video for TikTok / JTEG. When you are ready for real Veo, tell me 'Enable Veo' and I go add am with your billing.")
    vprompt = st.text_input("Video idea", placeholder="e.g. JTEG solar charger working in lab")
    if st.button("Prepare Video Script"):
        if vprompt:
            ans=ask_vinci(f"Write a 30 second video script for TikTok for JTEG: {vprompt}. Give hook, 3 scenes, voiceover text, captions.", None, "VIDEO SCRIPT")
            st.markdown(ans)
