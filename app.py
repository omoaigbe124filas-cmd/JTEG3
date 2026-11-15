
import streamlit as st
import sqlite3, os, io, json, re, smtplib, secrets, hashlib, urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage

import httpx
import plotly.graph_objects as go
from PIL import Image
from google import genai
from google.genai import types
from pypdf import PdfReader
from docx import Document

try:
    import bcrypt
except ImportError:
    bcrypt = None

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

try:
    import edge_tts
    import asyncio
except ImportError:
    edge_tts = None

# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# ============================================================
st.set_page_config(
    page_title="Vinci AI | JTEG Intelligence Platform",
    page_icon="🤖", layout="wide", initial_sidebar_state="expanded"
)

APP_NAME = "Vinci AI"
DB_DIR = Path(os.getenv("VINCI_DATA_DIR", "vinci_data"))
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "vinci.sqlite3"
LOGO_PATH = Path(os.getenv("VINCI_LOGO_PATH", "logo.png"))
PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3.8-flash"

SYSTEM_PROMPT = """
You are Vinci AI, the engineering intelligence assistant of Josiah
Technologies and Engineering Group (JTEG), the JTEG Intelligence Platform.
Help with engineering education, research, mathematics, physics,
programming, calculations, technical documentation, CAD concepts and design.
Show equations and units when useful. State assumptions and uncertainty.
Never claim a simulation or web search was performed unless it was.
For electrical topics, keep guidance educational and simulation-focused;
do not provide hazardous live-testing or high-voltage construction steps.
"""

# --------------------------- Styling ---------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');
:root{--cyan:#35d8ef;--blue:#2475d8}
.stApp{background:radial-gradient(circle at 15% 5%,rgba(20,105,145,.19),transparent 38%),linear-gradient(135deg,#091321,#101e31,#0b1725);background-attachment:fixed;font-family:'DM Sans',sans-serif}
[data-testid="stSidebar"]{background:#0a1421;border-right:1px solid rgba(80,190,220,.2)}
h1,h2,h3{font-family:'Space Grotesk',sans-serif}
.stButton button,.stDownloadButton button{border-radius:11px;border:1px solid rgba(53,216,239,.5);background:linear-gradient(110deg,#116b99,#2856a9);color:white;font-weight:600;min-height:40px}
[data-testid="stChatMessage"]{border-radius:15px;border:1px solid rgba(100,200,240,.12);background:rgba(255,255,255,.035)}
.hero{padding:22px;border:1px solid rgba(70,200,230,.3);border-radius:18px;background:linear-gradient(120deg,rgba(14,107,143,.25),rgba(29,56,105,.22))}
.muted{color:#9bb4c9}
</style>
""", unsafe_allow_html=True)

def cfg(name, default=""):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)

GEMINI_KEY = cfg("GEMINI_API_KEY")
SMTP_HOST = cfg("SMTP_HOST")
SMTP_PORT = int(cfg("SMTP_PORT", "587") or 587)
SMTP_USER = cfg("SMTP_USER")
SMTP_PASSWORD = cfg("SMTP_PASSWORD")
SMTP_FROM = cfg("SMTP_FROM", SMTP_USER)
ADMIN_EMAIL = cfg("ADMIN_EMAIL").strip().lower()

# --------------------------- Database ---------------------------
def db():
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def utcnow():
    return datetime.now(timezone.utc)

def stamp():
    return utcnow().isoformat()

def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE, phone TEXT NOT NULL, job TEXT NOT NULL,
          password_hash BLOB NOT NULL, verified INTEGER DEFAULT 0,
          role TEXT DEFAULT 'user', created_at TEXT NOT NULL,
          last_login TEXT, login_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS verification_codes(
          email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, purpose TEXT NOT NULL,
          expires_at TEXT NOT NULL, attempts INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS conversations(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          title TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS projects(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          name TEXT NOT NULL, description TEXT, status TEXT DEFAULT 'Planning',
          created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS reminders(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          title TEXT NOT NULL, due TEXT, notes TEXT, completed INTEGER DEFAULT 0,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          filename TEXT, content TEXT, created_at TEXT,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS usage_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          event TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)
        # Promote only the configured admin email. Admin access is not user-selectable.
        if ADMIN_EMAIL:
            c.execute("UPDATE users SET role='admin' WHERE email=?", (ADMIN_EMAIL,))

init_db()

# --------------------------- Email / Authentication ---------------------------
def hash_code(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()

def send_email(to_addr, subject, body):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD and SMTP_FROM):
        raise RuntimeError("Email is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and SMTP_FROM in hosting Secrets.")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, SMTP_FROM, to_addr
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=25) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)

def issue_code(email, purpose):
    code = f"{secrets.randbelow(1_000_000):06d}"
    expiry = (utcnow() + timedelta(minutes=10)).isoformat()
    with db() as c:
        c.execute("""INSERT INTO verification_codes(email,code_hash,purpose,expires_at,attempts)
          VALUES(?,?,?,?,0) ON CONFLICT(email) DO UPDATE SET
          code_hash=excluded.code_hash,purpose=excluded.purpose,
          expires_at=excluded.expires_at,attempts=0""",
          (email, hash_code(code), purpose, expiry))
    send_email(email, "Your Vinci AI verification code", 
               f"Your Vinci AI code is {code}. It expires in 10 minutes. If you did not request it, ignore this email.")

def check_code(email, code, purpose):
    with db() as c:
        row = c.execute("SELECT * FROM verification_codes WHERE email=?", (email,)).fetchone()
        if not row or row["purpose"] != purpose:
            return False
        if row["attempts"] >= 5 or utcnow() > datetime.fromisoformat(row["expires_at"]):
            c.execute("DELETE FROM verification_codes WHERE email=?", (email,))
            return False
        if secrets.compare_digest(row["code_hash"], hash_code(code.strip())):
            c.execute("DELETE FROM verification_codes WHERE email=?", (email,))
            return True
        c.execute("UPDATE verification_codes SET attempts=attempts+1 WHERE email=?", (email,))
        return False

def password_hash(password):
    if bcrypt is None:
        raise RuntimeError("bcrypt is missing. Install requirements.txt.")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))

def password_ok(password, saved):
    return bcrypt is not None and bcrypt.checkpw(password.encode(), saved)

def set_user(user_id):
    with db() as c:
        row = c.execute("SELECT id,full_name,email,role FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return
        st.session_state.auth_user = dict(row)
        c.execute("UPDATE users SET last_login=?,login_count=login_count+1 WHERE id=?", (stamp(), user_id))
        c.execute("INSERT INTO usage_events(user_id,event,created_at) VALUES(?,?,?)", (user_id,"login",stamp()))
    st.session_state.cid = None
    st.session_state.document_context = ""

def auth_screen():
    st.markdown('<div class="hero"><div class="muted">JOSIAH TECHNOLOGIES AND ENGINEERING GROUP</div><h1>VINCI AI</h1><h3>JTEG Intelligence Platform</h3><p class="muted">Engineering knowledge. Research. Design. Intelligence.</p></div>', unsafe_allow_html=True)
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=210)
    st.caption("Made in Nigeria. Built for the World.")
    login_tab, signup_tab, recover_tab = st.tabs(["Login", "Create New Account", "Forgot password"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email address").strip().lower()
            password = st.text_input("Password", type="password")
            go = st.form_submit_button("Login", use_container_width=True)
        if go:
            with db() as c:
                user = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user and password_ok(password, user["password_hash"]):
                if not user["verified"]:
                    st.warning("Verify your email before logging in.")
                else:
                    set_user(user["id"]); st.rerun()
            else:
                st.error("Email or password is incorrect.")

    with signup_tab:
        st.caption("Create an account. Email verification is required before access.")
        with st.form("signup_form"):
            full_name = st.text_input("Full name")
            email = st.text_input("Email address", key="signup_email").strip().lower()
            phone = st.text_input("Phone number")
            job = st.text_input("Job description")
            password = st.text_input("Create password", type="password")
            confirm = st.text_input("Confirm password", type="password")
            submit = st.form_submit_button("Create account and send code", use_container_width=True)
        if submit:
            if not all([full_name.strip(), email, phone.strip(), job.strip(), password]):
                st.error("Complete all fields.")
            elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                st.error("Enter a valid email address.")
            elif len(password) < 10 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
                st.error("Use at least 10 characters, including letters and numbers.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                try:
                    with db() as c:
                        existing = c.execute("SELECT id,verified FROM users WHERE email=?", (email,)).fetchone()
                        if existing and existing["verified"]:
                            raise ValueError("An account already exists for this email.")
                        if existing:
                            c.execute("DELETE FROM users WHERE id=?", (existing["id"],))
                        c.execute("""INSERT INTO users(full_name,email,phone,job,password_hash,verified,role,created_at)
                          VALUES(?,?,?,?,?,0,?,?)""",
                          (full_name.strip(),email,phone.strip(),job.strip(),password_hash(password),
                           "admin" if email == ADMIN_EMAIL and ADMIN_EMAIL else "user",stamp()))
                    issue_code(email, "verify")
                    st.session_state.pending_email = email
                    st.success("Verification code sent. Enter it below.")
                except Exception as e:
                    st.error(str(e))
        if st.session_state.get("pending_email"):
            with st.form("verify_signup"):
                st.write(f"Verify: {st.session_state.pending_email}")
                code = st.text_input("Six-digit email code", max_chars=6)
                verify = st.form_submit_button("Verify email")
            if verify:
                email = st.session_state.pending_email
                if check_code(email, code, "verify"):
                    with db() as c:
                        c.execute("UPDATE users SET verified=1 WHERE email=?", (email,))
                        uid = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
                    st.session_state.pop("pending_email", None)
                    set_user(uid); st.success("Email verified."); st.rerun()
                else:
                    st.error("Code is invalid, expired, or has too many failed attempts.")

    with recover_tab:
        with st.form("recover_request"):
            email = st.text_input("Account email", key="recover_email").strip().lower()
            send = st.form_submit_button("Send reset code")
        if send:
            with db() as c:
                exists = c.execute("SELECT id FROM users WHERE email=? AND verified=1", (email,)).fetchone()
            if exists:
                try:
                    issue_code(email, "reset")
                    st.session_state.reset_email = email
                    st.success("If the account exists, a reset code has been sent.")
                except Exception as e:
                    st.error(str(e))
            else:
                st.info("If the account exists, a reset code has been sent.")
        if st.session_state.get("reset_email"):
            with st.form("recover_finish"):
                code = st.text_input("Six-digit reset code", max_chars=6)
                newp = st.text_input("New password", type="password")
                newp2 = st.text_input("Confirm new password", type="password")
                reset = st.form_submit_button("Reset password")
            if reset:
                email = st.session_state.reset_email
                if len(newp) < 10 or not re.search(r"\d",newp) or newp != newp2:
                    st.error("Passwords must match and be at least 10 characters with a number.")
                elif check_code(email, code, "reset"):
                    with db() as c:
                        c.execute("UPDATE users SET password_hash=? WHERE email=?", (password_hash(newp),email))
                    st.session_state.pop("reset_email",None)
                    st.success("Password updated. You can now log in.")
                else:
                    st.error("Code invalid or expired.")
    st.stop()

# --------------------------- Authentication gate ---------------------------
if "auth_user" not in st.session_state:
    st.session_state.auth_user = None
if not st.session_state.auth_user:
    auth_screen()

USER = st.session_state.auth_user
UID = int(USER["id"])
IS_ADMIN = USER["role"] == "admin"

def log_event(event):
    with db() as c:
        c.execute("INSERT INTO usage_events(user_id,event,created_at) VALUES(?,?,?)",(UID,event,stamp()))

# --------------------------- Gemini engine ---------------------------
@st.cache_resource
def gemini_client(api_key):
    return genai.Client(api_key=api_key) if api_key else None

def gemini_request(contents, temperature=0.5):
    client = gemini_client(GEMINI_KEY)
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is missing from hosting Secrets.")
    last_error = None
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            result = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT, temperature=temperature
                )
            )
            log_event("gemini_request")
            return result
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Both Gemini models failed. Last error: {last_error}")

def create_conversation():
    with db() as c:
        cur = c.execute("INSERT INTO conversations(user_id,title,created_at) VALUES(?,?,?)",(UID,"New conversation",stamp()))
        return cur.lastrowid

def owned_conversation(cid):
    with db() as c:
        return c.execute("SELECT id FROM conversations WHERE id=? AND user_id=?",(cid,UID)).fetchone() is not None

def save_message(cid, role, content):
    if not owned_conversation(cid):
        raise PermissionError("Conversation does not belong to this account.")
    with db() as c:
        c.execute("INSERT INTO messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)",(cid,role,content,stamp()))
        if role == "user":
            n = c.execute("SELECT COUNT(*) n FROM messages WHERE conversation_id=?",(cid,)).fetchone()["n"]
            if n == 1:
                c.execute("UPDATE conversations SET title=? WHERE id=? AND user_id=?",(content.replace("\n"," ")[:55],cid,UID))

def get_messages(cid):
    if not cid or not owned_conversation(cid):
        return []
    with db() as c:
        return c.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id",(cid,)).fetchall()

def user_conversations():
    with db() as c:
        return c.execute("SELECT id,title FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 60",(UID,)).fetchall()

def ask_vinci(cid, prompt, image_bytes=None, image_mime="image/jpeg", document=""):
    rows = list(get_messages(cid)[-30:])
    # The caller saves the current user message before requesting Gemini.
    # Remove that final turn from history and re-add it once with attachments.
    if rows and rows[-1]["role"] == "user" and rows[-1]["content"] == prompt:
        rows = rows[:-1]
    history = []
    for row in rows:
        history.append(types.Content(role="user" if row["role"]=="user" else "model",
                                     parts=[types.Part.from_text(text=row["content"])]))
    parts = [types.Part.from_text(text=prompt)]
    if document:
        parts.append(types.Part.from_text(text="\nDOCUMENT CONTEXT:\n"+document[:25000]))
    if image_bytes:
        parts.append(types.Part.from_bytes(data=image_bytes,mime_type=image_mime))
    history.append(types.Content(role="user",parts=parts))
    response = gemini_request(history)
    return response.text or "Vinci could not generate a response."

# --------------------------- Utilities ---------------------------
def extract_document(upload):
    data, name = upload.getvalue(), upload.name.lower()
    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(f"PAGE {i+1}\n{p.extract_text() or ''}" for i,p in enumerate(reader.pages))
    if name.endswith(".docx"):
        doc = Document(io.BytesIO(data))
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows: lines.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(lines)
    if name.endswith((".txt",".md",".csv",".json",".py")):
        return data.decode("utf-8",errors="replace")
    raise ValueError("Unsupported document type.")

def free_image(prompt, width, height):
    url = "https://image.pollinations.ai/prompt/"+urllib.parse.quote(prompt,safe="")+f"?width={width}&height={height}&model=flux&nologo=true&safe=true"
    with httpx.Client(timeout=180,follow_redirects=True) as client:
        r=client.get(url); r.raise_for_status()
    Image.open(io.BytesIO(r.content)).verify()
    return r.content

def research(query, limit):
    if DDGS is None: raise RuntimeError("ddgs is not installed.")
    with DDGS() as ddgs:
        rows=ddgs.text(query,max_results=limit)
    return [{"title":x.get("title",""),"url":x.get("href",""),"body":x.get("body","")} for x in rows]

def make_speech(text):
    if edge_tts is None: raise RuntimeError("edge-tts is not installed.")
    async def run():
        comm=edge_tts.Communicate(text,"en-NG-AbeoNeural")
        out=bytearray()
        async for chunk in comm.stream():
            if chunk["type"]=="audio": out.extend(chunk["data"])
        return bytes(out)
    try: return asyncio.run(run())
    except RuntimeError:
        loop=asyncio.new_event_loop()
        try: return loop.run_until_complete(run())
        finally: loop.close()

# --------------------------- DC Circuit Lab (built-in solver) ---------------------------
# Deliberately uses NumPy already required by Streamlit; no PySpice/Ngspice,
# serial hardware access, or external schematic package is required.
def solve_dc(resistors, sources, ground="0"):
    nodes=set()
    for a,b,_ in resistors: nodes.update([a,b])
    for a,b,_ in sources: nodes.update([a,b])
    nodes.discard(ground)
    nodes=sorted(nodes)
    if not nodes: return {ground:0.0}, []
    # Modified nodal analysis: node voltages + ideal voltage-source currents.
    import numpy as np
    n,m=len(nodes),len(sources)
    index={node:i for i,node in enumerate(nodes)}
    A=np.zeros((n+m,n+m),dtype=float); z=np.zeros(n+m,dtype=float)
    for a,b,r in resistors:
        r=float(r)
        if r<=0: raise ValueError("Resistance must be greater than zero.")
        g=1.0/r
        if a!=ground: A[index[a],index[a]]+=g
        if b!=ground: A[index[b],index[b]]+=g
        if a!=ground and b!=ground:
            A[index[a],index[b]]-=g; A[index[b],index[a]]-=g
    for k,(a,b,v) in enumerate(sources):
        col=n+k
        if a!=ground: A[index[a],col]+=1; A[col,index[a]]+=1
        if b!=ground: A[index[b],col]-=1; A[col,index[b]]-=1
        z[col]=float(v)
    try: x=np.linalg.solve(A,z)
    except Exception as e: raise ValueError("Circuit has no unique DC solution. Check floating nodes, shorts and source connections.") from e
    volts={ground:0.0}
    volts.update({node:float(x[i]) for node,i in index.items()})
    currents=[]
    for a,b,r in resistors:
        currents.append({"from":a,"to":b,"resistance":float(r),
                         "current_A":(volts[a]-volts[b])/float(r)})
    return volts,currents

def draw_circuit(resistors,sources,volts):
    fig=go.Figure()
    nodes=set()
    for a,b,r in resistors: nodes.update([a,b])
    for a,b,v in sources: nodes.update([a,b])
    ordered=sorted(nodes)
    pos={node:(i,0) for i,node in enumerate(ordered)}
    for a,b,r in resistors:
        x1,y1=pos[a]; x2,y2=pos[b]
        fig.add_trace(go.Scatter(x=[x1,x2],y=[y1,y2],mode="lines+text",
            text=["",f"{r:g} Ω"],textposition="top center",name=f"R {r:g}Ω",
            line=dict(width=4,color="#39c8e8")))
    for a,b,v in sources:
        x1,y1=pos[a]; x2,y2=pos[b]
        fig.add_trace(go.Scatter(x=[x1,x2],y=[y1-.12,y2-.12],mode="lines+text",
            text=["",f"{v:g} V"],textposition="bottom center",name="Voltage source",
            line=dict(width=3,dash="dot",color="#e7b95a")))
    for node,(x,y) in pos.items():
        fig.add_trace(go.Scatter(x=[x],y=[y],mode="markers+text",
            text=[f"{node}  ({volts.get(node,0):.3g} V)"],textposition="top center",
            marker=dict(size=12),showlegend=False))
    fig.update_layout(height=300,margin=dict(l=10,r=10,t=20,b=20),
        xaxis=dict(visible=False),yaxis=dict(visible=False),showlegend=False)
    return fig

# --------------------------- Session defaults ---------------------------
for key, default in {
    "cid":None,"page":"Chat","document_context":"","last_image":None,
    "voice_answer":"","research_results":[],"design_result":None
}.items():
    if key not in st.session_state: st.session_state[key]=default
if st.session_state.cid is None or not owned_conversation(st.session_state.cid):
    st.session_state.cid=create_conversation()

# --------------------------- Sidebar ---------------------------
PAGES=["Chat","Voice","Image Studio","Design Studio","DC Circuit Lab","Research","Projects","Documents","Settings"]
with st.sidebar:
    if LOGO_PATH.exists(): st.image(str(LOGO_PATH),use_container_width=True)
    st.markdown("## 🤖 Vinci AI")
    st.caption("JTEG Intelligence Platform")
    st.caption(f"Signed in: {USER['full_name']}")
    if GEMINI_KEY: st.success("Gemini configured")
    else: st.warning("Gemini API key missing")
    if st.button("＋ New chat",use_container_width=True):
        st.session_state.cid=create_conversation(); st.session_state.page="Chat"; st.rerun()
    st.radio("Workspace",PAGES,key="page",label_visibility="collapsed")
    st.divider()
    st.markdown("### Your conversations")
    for item in user_conversations():
        a,b=st.columns([4,1])
        if a.button(item["title"][:26],key=f"open_{item['id']}",use_container_width=True):
            st.session_state.cid=item["id"]; st.session_state.page="Chat"; st.rerun()
        if b.button("×",key=f"del_{item['id']}"):
            with db() as c: c.execute("DELETE FROM conversations WHERE id=? AND user_id=?",(item["id"],UID))
            if item["id"]==st.session_state.cid: st.session_state.cid=create_conversation()
            st.rerun()
    st.divider()
    if IS_ADMIN:
        st.caption("Administrator account")
        if st.button("Admin dashboard",use_container_width=True):
            st.session_state.page="Admin"; st.rerun()
    if st.button("Log out",use_container_width=True):
        st.session_state.auth_user=None
        for k in ["cid","document_context","pending_email","reset_email"]:
            st.session_state.pop(k,None)
        st.rerun()

# --------------------------- Header ---------------------------
st.markdown('<div class="hero"><div class="muted">JOSIAH TECHNOLOGIES AND ENGINEERING GROUP</div><h1 style="margin:4px 0;color:white">VINCI AI</h1><h3 style="margin:0;color:#55dff5">JTEG Intelligence Platform</h3><p class="muted">Engineering knowledge. Research. Design. Intelligence.</p></div>',unsafe_allow_html=True)

page=st.session_state.page

# --------------------------- Chat ---------------------------
if page=="Chat":
    st.subheader("Ask Vinci AI anything")
    for m in get_messages(st.session_state.cid):
        with st.chat_message(m["role"]): st.markdown(m["content"])
    upload=st.file_uploader("Attach an image or document",type=["pdf","docx","txt","md","csv","png","jpg","jpeg","webp"],key="chat_file")
    image_bytes=None; image_mime="image/jpeg"
    if upload:
        ext=Path(upload.name).suffix.lower()
        if ext in [".png",".jpg",".jpeg",".webp"]:
            image_bytes=upload.getvalue(); image_mime=upload.type or image_mime
            st.image(image_bytes,width=180)
        else:
            try:
                st.session_state.document_context=extract_document(upload)[:25000]
                st.success("Document attached for this chat.")
            except Exception as e: st.error(str(e))
    prompt=st.chat_input("Ask Vinci AI anything...")
    if prompt:
        save_message(st.session_state.cid,"user",prompt)
        with st.chat_message("user"): st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Vinci is thinking..."):
                try:
                    answer=ask_vinci(st.session_state.cid,prompt,image_bytes,image_mime,st.session_state.document_context)
                    st.markdown(answer); save_message(st.session_state.cid,"assistant",answer)
                    st.session_state.document_context=""
                except Exception as e: st.error(f"Vinci error: {e}")

# --------------------------- Voice ---------------------------
elif page=="Voice":
    st.subheader("Vinci Voice")
    st.info("Push-to-talk voice input. This is not a continuous live voice connection.")
    audio=st.audio_input("Record a message")
    if audio and st.button("Transcribe and send"):
        try:
            client=gemini_client(GEMINI_KEY)
            resp=client.models.generate_content(model=PRIMARY_MODEL,contents=[
                "Transcribe this audio accurately. Return only the transcription.",
                types.Part.from_bytes(data=audio.getvalue(),mime_type=audio.type or "audio/wav")])
            transcript=resp.text or ""
            st.write("**Transcription:**",transcript)
            if transcript.strip():
                save_message(st.session_state.cid,"user",transcript)
                answer=ask_vinci(st.session_state.cid,transcript)
                save_message(st.session_state.cid,"assistant",answer)
                st.session_state.voice_answer=answer; st.markdown(answer)
        except Exception as e: st.error(str(e))
    if st.session_state.voice_answer and st.button("Read answer aloud"):
        try: st.audio(make_speech(st.session_state.voice_answer),format="audio/mp3")
        except Exception as e: st.error(str(e))

# --------------------------- Image Studio ---------------------------
elif page=="Image Studio":
    st.subheader("Vinci Image Studio")
    st.info("Uses a third-party image service. It is not a paid Gemini image-generation API; availability and free access are controlled by that provider.")
    prompt=st.text_area("Describe the image",height=110)
    fmt=st.selectbox("Format",["Square","Portrait","Landscape"])
    dims={"Square":(1024,1024),"Portrait":(768,1024),"Landscape":(1024,768)}
    if st.button("Generate image"):
        if not prompt.strip(): st.warning("Enter a description.")
        else:
            try:
                with st.spinner("Generating image..."):
                    w,h=dims[fmt]; st.session_state.last_image=free_image(prompt,w,h)
            except Exception as e: st.error(f"Image service unavailable: {e}")
    if st.session_state.last_image:
        st.image(st.session_state.last_image,use_container_width=True)
        st.download_button("Download image",st.session_state.last_image,"vinci_image.png","image/png")

# --------------------------- Design Studio ---------------------------
elif page=="Design Studio":
    st.subheader("Engineering Design Studio")
    st.caption("Lightweight parametric 2D/3D geometry and photo-assisted estimates. This is not a manufacturing-ready CAD package.")
    mode=st.radio("Design mode",["3D Model","2D Drawing","Photo-to-Design"],horizontal=True)
    if mode=="3D Model":
        with st.form("manual_3d"):
            a,b,c=st.columns(3)
            L=a.number_input("Length (mm)",1.,5000.,300.)
            W=b.number_input("Width (mm)",1.,5000.,200.)
            H=c.number_input("Height (mm)",1.,5000.,100.)
            make=st.form_submit_button("Create 3D model")
        if make:
            st.session_state.design_result={"name":"Custom enclosure","components":[{"name":"Main body","dimensions":[L,W,H],"position":[0,0,0],"color":"#38a9d8"}]}
    elif mode=="2D Drawing":
        with st.form("manual_2d"):
            L=st.number_input("Length (mm)",1.,5000.,300.)
            W=st.number_input("Width (mm)",1.,5000.,200.)
            make=st.form_submit_button("Create 2D drawing")
        if make:
            st.session_state.design_result={"name":"2D component","components":[{"name":"Main body","dimensions":[L,W,10.],"position":[0,0,0],"color":"#38a9d8"}]}
    else:
        photo=st.file_uploader("Upload an object photograph",type=["png","jpg","jpeg","webp"],key="photo_design")
        if photo and st.button("Analyze photo"):
            try:
                client=gemini_client(GEMINI_KEY)
                prompt=("Analyze only visible parts of this object. Return JSON with keys name, components. Each component: name, dimensions_mm [x,y,z] (estimates only), position_mm [x,y,z], color hex, description. Hidden parts must be labeled estimated. Never claim exact dimensions from a photo.")
                resp=client.models.generate_content(model=PRIMARY_MODEL,contents=[prompt,types.Part.from_bytes(data=photo.getvalue(),mime_type=photo.type or "image/jpeg")],config=types.GenerateContentConfig(response_mime_type="application/json"))
                data=json.loads(resp.text)
                comps=[]
                for x in data.get("components",[])[:12]:
                    d=x.get("dimensions_mm",[50,50,50]); p=x.get("position_mm",[0,0,0])
                    if len(d)==3 and len(p)==3:
                        comps.append({"name":str(x.get("name","Part")),"dimensions":[max(1,float(v)) for v in d],"position":[float(v) for v in p],"color":x.get("color","#55aadd"),"description":x.get("description","Estimated from image")})
                if not comps: raise ValueError("No components returned.")
                st.session_state.design_result={"name":data.get("name","Analyzed object"),"components":comps}
            except Exception as e: st.error(f"Photo analysis failed: {e}")
    design=st.session_state.design_result
    if design:
        st.markdown(f"### {design['name']}")
        explode=st.slider("Exploded-view separation",0.,150.,0.)
        fig=go.Figure()
        for i,p in enumerate(design["components"]):
            x,y,z=p["position"]; dx,dy,dz=p["dimensions"]
            fig.add_trace(go.Mesh3d(x=[x+i*explode,x+dx+i*explode,x+dx+i*explode,x+i*explode],y=[y,y,y+dy,y+dy],z=[z,z,z,z],i=[0,0],j=[1,2],k=[2,3],opacity=.6,color=p["color"],name=p["name"]))
            fig.add_trace(go.Scatter3d(x=[x+i*explode+dx/2],y=[y+dy/2],z=[z+dz],mode="text",text=[p["name"]],showlegend=False))
        fig.update_layout(height=480,scene=dict(aspectmode="data",xaxis_title="X mm",yaxis_title="Y mm",zaxis_title="Z mm"))
        st.plotly_chart(fig,use_container_width=True)
        for p in design["components"]: st.write(f"**{p['name']}** — {p['dimensions']} mm. {p.get('description','')}")
        st.download_button("Download component data (JSON)",json.dumps(design,indent=2),"vinci_design.json","application/json")

# --------------------------- DC Circuit Lab ---------------------------
elif page=="DC Circuit Lab":
    st.subheader("DC Circuit Design Lab")
    st.info("Educational DC resistive-network solver using modified nodal analysis. This version does not require PySpice, Ngspice, Arduino hardware, or serial-port permissions.")
    st.markdown("**Circuit setup**")
    st.caption("Use node names such as 0, A, B. Node 0 is ground. Enter each resistor and voltage source in the tables.")
    with st.form("dc_circuit_form"):
        st.markdown("Resistors")
        rcount=st.number_input("Number of resistors",1,8,2)
        resistors=[]
        for i in range(int(rcount)):
            x,y,z=st.columns(3)
            a=x.text_input(f"R{i+1} node +",value="A" if i==0 else "B",key=f"ra{i}")
            b=y.text_input(f"R{i+1} node −",value="0",key=f"rb{i}")
            r=z.number_input(f"R{i+1} (Ω)",.001,1e9,100.0 if i==0 else 220.0,key=f"rv{i}")
            resistors.append((a.strip(),b.strip(),r))
        st.markdown("Independent DC voltage sources")
        scount=st.number_input("Number of voltage sources",1,4,1)
        sources=[]
        for i in range(int(scount)):
            x,y,z=st.columns(3)
            a=x.text_input(f"V{i+1} positive node",value="A",key=f"sa{i}")
            b=y.text_input(f"V{i+1} negative node",value="0",key=f"sb{i}")
            v=z.number_input(f"V{i+1} (V)",-1000.,1000.,12.0,key=f"sv{i}")
            sources.append((a.strip(),b.strip(),v))
        run=st.form_submit_button("Solve DC circuit")
    if run:
        try:
            if any(not a or not b or a==b for a,b,_ in resistors+sources): raise ValueError("Every component needs two different node names.")
            volts,currents=solve_dc(resistors,sources)
            st.session_state.dc_result={"volts":volts,"currents":currents,"resistors":resistors,"sources":sources}
        except Exception as e: st.error(str(e))
    result=st.session_state.get("dc_result")
    if result:
        st.markdown("### Results")
        st.write("**Node voltages (V)**",result["volts"])
        st.dataframe(result["currents"],use_container_width=True)
        st.caption("Resistor current is positive from the first entered node to the second. This is a software calculation, not a physical test.")
        st.plotly_chart(draw_circuit(result["resistors"],result["sources"],result["volts"]),use_container_width=True)
        st.download_button("Download results (JSON)",json.dumps(result,indent=2),"dc_circuit_results.json","application/json")
    st.divider()
    st.markdown("**Capacitors, inductors and AC analysis:** not included in this lightweight release. SciPy-based transient/AC analysis can be added as a separate tested module later. Drag-and-drop Schemdraw, PySpice/Ngspice simulation and physical Arduino uploads are intentionally omitted rather than presented as working features.")

# --------------------------- Research ---------------------------
elif page=="Research":
    st.subheader("Research")
    query=st.text_input("Research question")
    limit=st.slider("Number of sources",3,10,6)
    if st.button("Search sources"):
        try: st.session_state.research_results=research(query,limit) if query.strip() else []
        except Exception as e: st.error(str(e))
    results=st.session_state.research_results
    for i,item in enumerate(results,1):
        with st.container(border=True):
            st.markdown(f"**[S{i}] {item['title']}**")
            st.write(item["body"])
            if item["url"]: st.markdown(f"[Open source]({item['url']})")
    if results and st.button("Analyze research with Vinci"):
        source_text="\n\n".join(f"[S{i}] {x['title']}\n{x['url']}\n{x['body']}" for i,x in enumerate(results,1))
        try:
            answer=gemini_request("Analyze these sources, compare evidence, state limitations and cite S numbers:\n"+source_text).text or ""
            st.markdown(answer)
        except Exception as e: st.error(str(e))

# --------------------------- Projects ---------------------------
elif page=="Projects":
    st.subheader("Project workspace")
    with st.form("project_add"):
        name=st.text_input("Project name"); desc=st.text_area("Description")
        add=st.form_submit_button("Save project")
    if add and name.strip():
        with db() as c: c.execute("INSERT INTO projects(user_id,name,description,created_at) VALUES(?,?,?,?)",(UID,name,desc,stamp()))
        st.success("Project saved."); st.rerun()
    with db() as c: projects=c.execute("SELECT * FROM projects WHERE user_id=? ORDER BY id DESC",(UID,)).fetchall()
    for p in projects:
        with st.container(border=True):
            st.markdown(f"**{p['name']}**"); st.write(p["description"])
            statuses=["Planning","In progress","On hold","Completed"]
            current=st.selectbox("Status",statuses,index=statuses.index(p["status"]),key=f"status{p['id']}")
            if current!=p["status"]:
                with db() as c: c.execute("UPDATE projects SET status=? WHERE id=? AND user_id=?",(current,p["id"],UID))
                st.rerun()
            if st.button("Delete project",key=f"pd{p['id']}"):
                with db() as c: c.execute("DELETE FROM projects WHERE id=? AND user_id=?",(p["id"],UID))
                st.rerun()
    st.divider(); st.markdown("### Reminders")
    with st.form("reminder_add"):
        title=st.text_input("Reminder"); due=st.date_input("Due date"); notes=st.text_area("Notes")
        addrem=st.form_submit_button("Add reminder")
    if addrem and title.strip():
        with db() as c: c.execute("INSERT INTO reminders(user_id,title,due,notes) VALUES(?,?,?,?)",(UID,title,due.isoformat(),notes))
        st.rerun()
    with db() as c: reminders=c.execute("SELECT * FROM reminders WHERE user_id=? ORDER BY due",(UID,)).fetchall()
    for r in reminders:
        done=st.checkbox(f"{r['title']} — {r['due']}",value=bool(r["completed"]),key=f"rem{r['id']}")
        if done!=bool(r["completed"]):
            with db() as c: c.execute("UPDATE reminders SET completed=? WHERE id=? AND user_id=?",(int(done),r["id"],UID))
            st.rerun()

# --------------------------- Documents ---------------------------
elif page=="Documents":
    st.subheader("Private document library")
    up=st.file_uploader("Upload PDF, Word or text document",type=["pdf","docx","txt","md","csv"])
    if up and st.button("Extract and save document"):
        try:
            content=extract_document(up)
            if not content.strip(): st.warning("No selectable text found. Scanned documents need OCR.")
            else:
                with db() as c: c.execute("INSERT INTO documents(user_id,filename,content,created_at) VALUES(?,?,?,?)",(UID,up.name,content,stamp()))
                st.success("Document saved privately.")
        except Exception as e: st.error(str(e))
    with db() as c: docs=c.execute("SELECT * FROM documents WHERE user_id=? ORDER BY id DESC",(UID,)).fetchall()
    for d in docs:
        with st.expander(d["filename"]):
            st.text_area("Extracted text",d["content"][:15000],height=180,key=f"doc{d['id']}")
            if st.button("Load into Chat",key=f"load{d['id']}"):
                st.session_state.document_context=d["content"][:25000]; st.session_state.page="Chat"; st.rerun()
            if st.button("Delete",key=f"dd{d['id']}"):
                with db() as c: c.execute("DELETE FROM documents WHERE id=? AND user_id=?",(d["id"],UID))
                st.rerun()

# --------------------------- Settings ---------------------------
elif page=="Settings":
    st.subheader("Account and platform settings")
    st.write("**Name:**",USER["full_name"])
    st.write("**Email:**",USER["email"])
    st.write("**AI primary:**",PRIMARY_MODEL)
    st.write("**Fallback:**",FALLBACK_MODEL)
    st.write("**Database:**",str(DB_PATH))
    st.caption("API keys and SMTP credentials must be configured in deployment Secrets, never committed to source control.")
    st.caption("This release uses a server-side Streamlit session for local email/password authentication. For persistent cross-browser/device login, configure a trusted OIDC provider or a production identity service.")

# --------------------------- Admin ---------------------------
elif page=="Admin":
    if not IS_ADMIN:
        st.error("Administrator access required."); st.stop()
    st.subheader("JTEG Administrator Dashboard")
    st.warning("Privacy boundary: this dashboard displays account and usage metadata only. It does not query or display private messages, documents, prompts, or project content.")
    with db() as c:
        users=c.execute("""SELECT id,full_name,email,phone,job,verified,created_at,last_login,login_count,role
                           FROM users ORDER BY created_at DESC""").fetchall()
        counts=c.execute("SELECT event,COUNT(*) n FROM usage_events GROUP BY event").fetchall()
    st.metric("Registered accounts",len(users))
    st.dataframe([dict(x) for x in users],use_container_width=True)
    st.markdown("### Platform usage totals")
    st.dataframe([dict(x) for x in counts],use_container_width=True)

# --------------------------- Footer ---------------------------
st.divider()
st.markdown('<div style="text-align:center;color:#91afc4;padding:14px"><b>VINCI AI</b><br>JTEG INTELLIGENCE PLATFORM<br>Made in Nigeria. Built for the World.</div>',unsafe_allow_html=True)
