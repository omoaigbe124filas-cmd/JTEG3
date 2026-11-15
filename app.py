
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
    
