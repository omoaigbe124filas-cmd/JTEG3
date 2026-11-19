
# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 1 OF 6
# FOUNDATION, CONFIGURATION AND POSTGRESQL DATABASE
# ============================================================

import os
import re
import io
import json
import uuid
import time
import base64
import hashlib
import secrets
import logging
import mimetypes
from pathlib import Path
from datetime import datetime, timezone, timedelta
from functools import wraps

import streamlit as st
import httpx
import bcrypt

from sqlalchemy import (
    create_engine, text, inspect,
    Integer, String, Boolean
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool


# ============================================================
# 1. APPLICATION CONFIGURATION
# ============================================================

APP_NAME = "VINCI AI"
APP_VERSION = "4.0"
APP_BRAND = "JTEG INTELLIGENCE PLATFORM"

PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3.8-flash"

RESEARCH_PRIMARY_MODEL = "gemini-3.5-flash"
RESEARCH_FALLBACK_MODEL = "gemini-3.6-flash"

MAX_UPLOAD_MB = 15
MAX_DOCUMENT_CHARS = 50000

SESSION_DAYS = 30
VERIFICATION_MINUTES = 10
MAX_VERIFICATION_ATTEMPTS = 5

AI_POLICY = {
    "free_only": True,
    "paid_models": False,
    "automatic_purchases": False,
    "paid_fallback": False
}

OPENROUTER_POLICY = {
    "enabled": True,
    "research_only": True,
    "image_only_approved_free_models": True,
    "paid_models": False
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vinci")


# ============================================================
# 2. SECRET MANAGEMENT
# ============================================================

def get_secret(name, default=None):

    try:
        value = st.secrets.get(name)

        if value:
            return value

    except Exception:
        pass

    return os.environ.get(name, default)


DATABASE_URL = get_secret("DATABASE_URL")

GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")

OPENROUTER_RESEARCH_MODEL = get_secret(
    "OPENROUTER_RESEARCH_MODEL"
)

OPENROUTER_IMAGE_MODEL = get_secret(
    "OPENROUTER_IMAGE_MODEL"
)

SMTP_HOST = get_secret("SMTP_HOST")
SMTP_PORT = int(get_secret("SMTP_PORT", 587))
SMTP_USERNAME = get_secret("SMTP_USERNAME")
SMTP_PASSWORD = get_secret("SMTP_PASSWORD")
SMTP_FROM_EMAIL = get_secret("SMTP_FROM_EMAIL")

COOKIE_SECRET = get_secret("COOKIE_SECRET")

ADMIN_EMAILS = [
    item.strip().lower()
    for item in get_secret("ADMIN_EMAILS", "").split(",")
    if item.strip()
]


# ============================================================
# 3. STREAMLIT CONFIGURATION
# ============================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# 4. GENERAL UTILITIES
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def timestamp():
    return utc_now().isoformat()


def new_id():
    return str(uuid.uuid4())


def normalize_email(email):
    return str(email or "").strip().lower()


def hash_value(value):
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()


def safe_text(value, maximum=50000):
    return str(value or "").strip()[:maximum]


def generate_token():
    return secrets.token_urlsafe(48)


def database_ready():
    return bool(DATABASE_URL)


# ============================================================
# 5. POSTGRESQL ENGINE
# ============================================================

@st.cache_resource(show_spinner=False)
def get_database_engine():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing from Streamlit secrets."
        )

    url = DATABASE_URL.strip()

    if url.startswith("postgres://"):
        url = url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1
        )

    elif url.startswith("postgresql://"):
        url = url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1
        )

    return create_engine(
        url,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"connect_timeout": 15}
    )


def execute_sql(query, params=None, fetch=False):

    engine = get_database_engine()

    with engine.begin() as connection:

        result = connection.execute(
            text(query),
            params or {}
        )

        if fetch:
            return [dict(row) for row in result.mappings()]

        return result.rowcount


def test_database_connection():

    try:

        execute_sql("SELECT 1")

        return True

    except Exception as error:

        logger.exception("Database connection failed.")
        raise error


# ============================================================
# 6. DATABASE INITIALIZATION
# ============================================================

def initialize_database():

    statements = [

        """
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(36) PRIMARY KEY,
            full_name VARCHAR(200) NOT NULL,
            email VARCHAR(320) UNIQUE NOT NULL,
            phone VARCHAR(40),
            job_description TEXT,
            password_hash TEXT NOT NULL,
            is_verified BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            role VARCHAR(30) DEFAULT 'user',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            last_login TIMESTAMPTZ,
            login_count INTEGER DEFAULT 0
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS verification_codes (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            code_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            attempts INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS sessions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            revoked BOOLEAN DEFAULT FALSE
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            title VARCHAR(300) DEFAULT 'New conversation',
            is_archived BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS messages (
            id VARCHAR(36) PRIMARY KEY,
            conversation_id VARCHAR(36) NOT NULL
                REFERENCES conversations(id) ON DELETE CASCADE,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            role VARCHAR(30) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS saved_items (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            title VARCHAR(300),
            content TEXT,
            item_type VARCHAR(50) DEFAULT 'general',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS library_files (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            filename VARCHAR(500) NOT NULL,
            storage_path TEXT NOT NULL,
            file_type VARCHAR(100),
            file_size BIGINT DEFAULT 0,
            extracted_text TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS reminders (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            title VARCHAR(300) NOT NULL,
            description TEXT,
            reminder_time TIMESTAMPTZ NOT NULL,
            is_completed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS workspace_sessions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            workspace VARCHAR(100) NOT NULL,
            session_data JSONB DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, workspace)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS provider_usage (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            provider VARCHAR(100),
            model VARCHAR(200),
            workspace VARCHAR(100),
            success BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS admin_activity_logs (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            action VARCHAR(200),
            details TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS generated_images (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id)
                ON DELETE CASCADE,
            prompt TEXT,
            storage_path TEXT NOT NULL,
            model VARCHAR(200),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    ]

    indexes = [

        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",

        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",

        "CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at)",

        "CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)",

        "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)",

        "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)",

        "CREATE INDEX IF NOT EXISTS idx_saved_user ON saved_items(user_id)",

        "CREATE INDEX IF NOT EXISTS idx_library_user ON library_files(user_id)",

        "CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id)",

        "CREATE INDEX IF NOT EXISTS idx_provider_created ON provider_usage(created_at)",

        "CREATE INDEX IF NOT EXISTS idx_images_user ON generated_images(user_id)"
    ]

    engine = get_database_engine()

    with engine.begin() as connection:

        for statement in statements:
            connection.execute(text(statement))

        for statement in indexes:
            connection.execute(text(statement))

    return True


# ============================================================
# 7. DEFAULT SESSION STATE
# ============================================================

DEFAULT_STATE = {

    "auth_user": None,
    "authenticated": False,

    "pending_email": None,

    "page": "Chat",

    "conversation_id": None,

    "document_context": "",

    "chat_image": None,
    "chat_image_mime": None,

    "chat_uploaded_document_name": None,

    "research_result": None,

    "image_result": None,

    "voice_result": None,

    "workspace_sessions": {}
}

for key, value in DEFAULT_STATE.items():

    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 8. STARTUP DATABASE INITIALIZATION
# ============================================================

@st.cache_resource(show_spinner="Connecting to VINCI database...")
def vinci_initialize():

    test_database_connection()

    initialize_database()

    return True


try:

    vinci_initialize()

except Exception as error:

    st.error("VINCI AI database initialization failed.")

    st.code(str(error))

    st.info(
        "Check DATABASE_URL and confirm that PostgreSQL "
        "is accessible."
    )

    st.stop()


# ============================================================
# END OF BLOCK 1
# ============================================================

# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 2 OF 6
# AUTHENTICATION, REGISTRATION AND SECURITY
# ============================================================

import smtplib
from email.message import EmailMessage


# ============================================================
# 1. PASSWORD SECURITY
# ============================================================

def hash_password(password):

    password_bytes = password.encode("utf-8")

    return bcrypt.hashpw(
        password_bytes,
        bcrypt.gensalt(rounds=12)
    ).decode("utf-8")


def verify_password(password, stored_hash):

    try:

        return bcrypt.checkpw(
            password.encode("utf-8"),
            stored_hash.encode("utf-8")
        )

    except Exception:

        return False


# ============================================================
# 2. EMAIL DELIVERY
# ============================================================

def send_email(to_email, subject, body):

    if not all([
        SMTP_HOST,
        SMTP_USERNAME,
        SMTP_PASSWORD,
        SMTP_FROM_EMAIL
    ]):

        raise RuntimeError(
            "SMTP configuration is incomplete."
        )

    message = EmailMessage()

    message["Subject"] = subject
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = to_email

    message.set_content(body)

    with smtplib.SMTP(
        SMTP_HOST,
        SMTP_PORT,
        timeout=20
    ) as server:

        server.starttls()

        server.login(
            SMTP_USERNAME,
            SMTP_PASSWORD
        )

        server.send_message(message)

    return True


def send_verification_email(email, code):

    body = f"""
Welcome to VINCI AI.

Your email verification code is:

{code}

This code expires in {VERIFICATION_MINUTES} minutes.

If you did not create this account, you can ignore this email.

VINCI AI
JTEG Intelligence Platform
"""

    return send_email(
        email,
        "VINCI AI — Email Verification",
        body
    )


# ============================================================
# 3. USER LOOKUP
# ============================================================

def get_user_by_email(email):

    email = normalize_email(email)

    rows = execute_sql(
        """
        SELECT *
        FROM users
        WHERE email = :email
        LIMIT 1
        """,
        {"email": email},
        fetch=True
    )

    return rows[0] if rows else None


def get_user_by_id(user_id):

    rows = execute_sql(
        """
        SELECT *
        FROM users
        WHERE id = :user_id
        LIMIT 1
        """,
        {"user_id": str(user_id)},
        fetch=True
    )

    return rows[0] if rows else None


# ============================================================
# 4. ADMIN ROLE
# ============================================================

def sync_user_role(user_id):

    user = get_user_by_id(user_id)

    if not user:
        return False

    email = normalize_email(user["email"])

    role = "admin" if email in ADMIN_EMAILS else "user"

    execute_sql(
        """
        UPDATE users
        SET role = :role,
            updated_at = NOW()
        WHERE id = :user_id
        """,
        {
            "role": role,
            "user_id": str(user_id)
        }
    )

    return role


def current_user_is_admin():

    user = st.session_state.get("auth_user")

    if not isinstance(user, dict):
        return False

    fresh_user = get_user_by_id(user.get("id"))

    if not fresh_user:
        return False

    if not fresh_user.get("is_active"):
        return False

    role = sync_user_role(fresh_user["id"])

    return role == "admin"


# ============================================================
# 5. VERIFICATION CODE CREATION
# ============================================================

def create_verification_code(user_id):

    code = f"{secrets.randbelow(1000000):06d}"

    execute_sql(
        """
        DELETE FROM verification_codes
        WHERE user_id = :user_id
        """,
        {"user_id": str(user_id)}
    )

    execute_sql(
        """
        INSERT INTO verification_codes (
            id, user_id, code_hash, expires_at,
            attempts, created_at
        )
        VALUES (
            :id, :user_id, :code_hash, :expires_at,
            0, NOW()
        )
        """,
        {
            "id": new_id(),
            "user_id": str(user_id),
            "code_hash": hash_value(code),
            "expires_at": utc_now() + timedelta(
                minutes=VERIFICATION_MINUTES
            )
        }
    )

    return code


# ============================================================
# 6. USER REGISTRATION
# ============================================================

def register_user(
    full_name,
    email,
    phone,
    job_description,
    password
):

    full_name = safe_text(full_name, 200)
    email = normalize_email(email)
    phone = safe_text(phone, 40)
    job_description = safe_text(job_description, 1000)

    if not all([
        full_name,
        email,
        phone,
        job_description,
        password
    ]):

        raise ValueError(
            "All registration fields are required."
        )

    if not re.match(
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        email
    ):

        raise ValueError("Invalid email address.")

    if len(password) < 10:

        raise ValueError(
            "Password must contain at least 10 characters."
        )

    if get_user_by_email(email):

        raise ValueError(
            "An account with this email already exists."
        )

    user_id = new_id()

    password_hash = hash_password(password)

    execute_sql(
        """
        INSERT INTO users (
            id, full_name, email, phone,
            job_description, password_hash,
            is_verified, is_active, role,
            created_at, updated_at
        )
        VALUES (
            :id, :full_name, :email, :phone,
            :job_description, :password_hash,
            FALSE, TRUE, 'user',
            NOW(), NOW()
        )
        """,
        {
            "id": user_id,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "job_description": job_description,
            "password_hash": password_hash
        }
    )

    code = create_verification_code(user_id)

    try:

        send_verification_email(email, code)

    except Exception:

        logger.exception(
            "Verification email delivery failed."
        )

        raise RuntimeError(
            "Account was created, but verification email "
            "could not be sent. Check SMTP settings."
        )

    st.session_state["pending_email"] = email

    return True


# ============================================================
# 7. EMAIL VERIFICATION
# ============================================================

def verify_registration_code(email, code):

    email = normalize_email(email)
    code = str(code).strip()

    user = get_user_by_email(email)

    if not user:
        return False

    if user.get("is_verified"):
        return True

    rows = execute_sql(
        """
        SELECT *
        FROM verification_codes
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"user_id": user["id"]},
        fetch=True
    )

    if not rows:
        return False

    verification = rows[0]

    if verification["attempts"] >= MAX_VERIFICATION_ATTEMPTS:
        return False

    if verification["expires_at"] < utc_now():
        return False

    if not secrets.compare_digest(
        hash_value(code),
        verification["code_hash"]
    ):

        execute_sql(
            """
            UPDATE verification_codes
            SET attempts = attempts + 1
            WHERE id = :id
            """,
            {"id": verification["id"]}
        )

        return False

    execute_sql(
        """
        UPDATE users
        SET is_verified = TRUE,
            updated_at = NOW()
        WHERE id = :user_id
        """,
        {"user_id": user["id"]}
    )

    execute_sql(
        """
        DELETE FROM verification_codes
        WHERE user_id = :user_id
        """,
        {"user_id": user["id"]}
    )

    return True


# ============================================================
# 8. RESEND VERIFICATION CODE
# ============================================================

def resend_verification_code(email):

    email = normalize_email(email)

    user = get_user_by_email(email)

    if not user:
        return False

    if user.get("is_verified"):
        return True

    code = create_verification_code(user["id"])

    return send_verification_email(
        email,
        code
    )


# ============================================================
# 9. LOGIN ACTIVITY
# ============================================================

def record_login_activity(user_id):

    execute_sql(
        """
        UPDATE users
        SET last_login = NOW(),
            login_count = login_count + 1,
            updated_at = NOW()
        WHERE id = :user_id
        """,
        {"user_id": str(user_id)}
    )

    execute_sql(
        """
        INSERT INTO admin_activity_logs (
            id, user_id, action, details, created_at
        )
        VALUES (
            :id, :user_id, 'login',
            'User signed in', NOW()
        )
        """,
        {
            "id": new_id(),
            "user_id": str(user_id)
        }
    )


# ============================================================
# 10. CREATE USER SESSION
# ============================================================

def create_user_session(user_id):

    token = generate_token()

    token_hash = hash_value(token)

    expires_at = utc_now() + timedelta(
        days=SESSION_DAYS
    )

    execute_sql(
        """
        INSERT INTO sessions (
            id, user_id, token_hash,
            expires_at, created_at, revoked
        )
        VALUES (
            :id, :user_id, :token_hash,
            :expires_at, NOW(), FALSE
        )
        """,
        {
            "id": new_id(),
            "user_id": str(user_id),
            "token_hash": token_hash,
            "expires_at": expires_at
        }
    )

    st.session_state["vinci_session_token"] = token

    return token


# ============================================================
# 11. SESSION VALIDATION
# ============================================================

def validate_user_session(token):

    if not token:
        return None

    token_hash = hash_value(token)

    rows = execute_sql(
        """
        SELECT u.*
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = :token_hash
          AND s.revoked = FALSE
          AND s.expires_at > NOW()
          AND u.is_active = TRUE
          AND u.is_verified = TRUE
        LIMIT 1
        """,
        {"token_hash": token_hash},
        fetch=True
    )

    return rows[0] if rows else None


# ============================================================
# 12. RESTORE AUTHENTICATED SESSION
# ============================================================

def restore_authenticated_session():

    token = st.session_state.get(
        "vinci_session_token"
    )

    if not token:
        return False

    user = validate_user_session(token)

    if not user:
        return False

    st.session_state["auth_user"] = user
    st.session_state["authenticated"] = True

    return True


# ============================================================
# 13. REVOKE SESSION
# ============================================================

def revoke_user_session(token):

    if not token:
        return False

    execute_sql(
        """
        UPDATE sessions
        SET revoked = TRUE
        WHERE token_hash = :token_hash
        """,
        {"token_hash": hash_value(token)}
    )

    return True


# ============================================================
# 14. USER AUTHENTICATION
# ============================================================

def authenticate_user(email, password):

    email = normalize_email(email)

    user = get_user_by_email(email)

    if not user:
        return False

    if not user.get("is_active"):
        return False

    if not user.get("is_verified"):
        return False

    if not verify_password(
        password,
        user["password_hash"]
    ):

        return False

    sync_user_role(user["id"])

    record_login_activity(user["id"])

    create_user_session(user["id"])

    user = get_user_by_id(user["id"])

    st.session_state["auth_user"] = user
    st.session_state["authenticated"] = True

    return True


# ============================================================
# 15. LOGOUT
# ============================================================

def logout_user():

    token = st.session_state.get(
        "vinci_session_token"
    )

    if token:
        revoke_user_session(token)

    for key in [
        "vinci_session_token",
        "auth_user",
        "authenticated",
        "conversation_id",
        "document_context",
        "chat_image",
        "chat_image_mime",
        "chat_uploaded_document_name"
    ]:

        st.session_state.pop(key, None)

    return True


# ============================================================
# 16. ADMIN USER RECORDS
# ============================================================

def get_admin_user_records():

    return execute_sql(
        """
        SELECT
            id,
            full_name,
            email,
            role,
            is_verified,
            is_active,
            created_at,
            last_login,
            login_count
        FROM users
        ORDER BY created_at DESC
        LIMIT 500
        """,
        fetch=True
    )


# ============================================================
# 17. ADMIN STATISTICS
# ============================================================

def get_admin_statistics():

    queries = {

        "total_users": "SELECT COUNT(*) AS total FROM users",

        "verified_users": """
            SELECT COUNT(*) AS total
            FROM users WHERE is_verified = TRUE
        """,

        "total_conversations": """
            SELECT COUNT(*) AS total FROM conversations
        """,

        "total_messages": """
            SELECT COUNT(*) AS total FROM messages
        """,

        "total_images": """
            SELECT COUNT(*) AS total FROM generated_images
        """
    }

    statistics = {}

    for name, query in queries.items():

        result = execute_sql(
            query,
            fetch=True
        )

        statistics[name] = result[0]["total"]

    return statistics


# ============================================================
# END OF BLOCK 2
# ============================================================

# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 3 OF 6
# AI PROVIDERS, GEMINI, OPENROUTER AND MODEL ROUTING
# ============================================================

# ============================================================
# 1. PROVIDER CONFIGURATION
# ============================================================

GEMINI_API_BASE = (
    "https://generativelanguage.googleapis.com/v1beta/models"
)

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

AI_REQUEST_TIMEOUT = 90

AI_SYSTEM_INSTRUCTION = """
You are VINCI AI, the intelligent assistant of the
JTEG Intelligence Platform.

You are a capable, professional, accurate and helpful
AI assistant.

Your areas of assistance include:
- Engineering and technology
- Science and mathematics
- Software development
- Artificial intelligence
- Robotics and automation
- Business and entrepreneurship
- Education and research
- General knowledge and productivity

Give clear, structured and accurate answers.

Do not invent facts, sources, capabilities or results.
When uncertain, explain the uncertainty.

For engineering and technical subjects, explain
important safety limitations.
"""


# ============================================================
# 2. PROVIDER USAGE LOGGING
# ============================================================

def record_provider_usage(
    provider,
    model,
    workspace="Chat",
    success=True,
    user_id=None
):

    try:

        execute_sql(
            """
            INSERT INTO provider_usage (
                id, user_id, provider, model,
                workspace, success, created_at
            )
            VALUES (
                :id, :user_id, :provider, :model,
                :workspace, :success, NOW()
            )
            """,
            {
                "id": new_id(),
                "user_id": str(user_id) if user_id else None,
                "provider": safe_text(provider, 100),
                "model": safe_text(model, 200),
                "workspace": safe_text(workspace, 100),
                "success": bool(success)
            }
        )

    except Exception:

        logger.exception("Provider usage logging failed.")


# ============================================================
# 3. GEMINI REQUEST
# ============================================================

def call_gemini(
    prompt,
    history=None,
    model=None,
    system_instruction=None
):

    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini API key is missing.")

    selected_model = model or PRIMARY_MODEL

    url = (
        f"{GEMINI_API_BASE}/{selected_model}:generateContent"
    )

    contents = []

    for item in history or []:

        role = item.get("role", "user")

        if role not in ["user", "assistant", "model"]:
            continue

        gemini_role = (
            "model" if role == "assistant" else role
        )

        content = safe_text(item.get("content"), 30000)

        if content:
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content}]
            })

    contents.append({
        "role": "user",
        "parts": [{"text": safe_text(prompt, 50000)}]
    })

    payload = {
        "systemInstruction": {
            "parts": [{
                "text": system_instruction or AI_SYSTEM_INSTRUCTION
            }]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.95,
            "maxOutputTokens": 8192
        }
    }

    response = httpx.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=AI_REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Gemini returned HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    data = response.json()

    candidates = data.get("candidates", [])

    if not candidates:
        raise RuntimeError("Gemini returned no response.")

    parts = (
        candidates[0]
        .get("content", {})
        .get("parts", [])
    )

    answer = "\n".join(
        part.get("text", "")
        for part in parts
        if part.get("text")
    ).strip()

    if not answer:
        raise RuntimeError("Gemini returned empty text.")

    return answer


# ============================================================
# 4. OPENROUTER FREE MODEL VALIDATION
# ============================================================

def is_approved_free_model(model):

    model = str(model or "").strip()

    if not model:
        return False

    # Only explicitly identified free models are accepted.
    return model.endswith(":free")


# ============================================================
# 5. OPENROUTER REQUEST
# ============================================================

def call_openrouter(
    prompt,
    history=None,
    model=None,
    system_instruction=None
):

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OpenRouter API key is missing.")

    selected_model = model

    if not is_approved_free_model(selected_model):

        raise RuntimeError(
            "OpenRouter model rejected. "
            "Only models ending in :free are permitted."
        )

    messages = [{
        "role": "system",
        "content": system_instruction or AI_SYSTEM_INSTRUCTION
    }]

    for item in history or []:

        role = item.get("role", "user")

        if role not in ["user", "assistant"]:
            continue

        content = safe_text(item.get("content"), 30000)

        if content:
            messages.append({
                "role": role,
                "content": content
            })

    messages.append({
        "role": "user",
        "content": safe_text(prompt, 50000)
    })

    response = httpx.post(
        f"{OPENROUTER_API_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vinci-ai.streamlit.app",
            "X-Title": "VINCI AI"
        },
        json={
            "model": selected_model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 8192
        },
        timeout=AI_REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"OpenRouter returned HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    data = response.json()

    choices = data.get("choices", [])

    if not choices:
        raise RuntimeError("OpenRouter returned no response.")

    answer = (
        choices[0]
        .get("message", {})
        .get("content", "")
    )

    if isinstance(answer, list):

        answer = "\n".join(
            item.get("text", "")
            for item in answer
            if isinstance(item, dict)
        )

    answer = str(answer or "").strip()

    if not answer:
        raise RuntimeError("OpenRouter returned empty text.")

    return answer


# ============================================================
# 6. GENERAL CHAT MODEL ROUTER
# ============================================================

def generate_ai_response(
    prompt,
    history=None,
    workspace="Chat",
    user_id=None,
    system_instruction=None
):

    prompt = safe_text(prompt, MAX_DOCUMENT_CHARS)

    if not prompt:
        raise ValueError("Your message cannot be empty.")

    models = [
        PRIMARY_MODEL,
        FALLBACK_MODEL
    ]

    errors = []

    for model in models:

        try:

            answer = call_gemini(
                prompt=prompt,
                history=history,
                model=model,
                system_instruction=system_instruction
            )

            record_provider_usage(
                "Gemini",
                model,
                workspace,
                True,
                user_id
            )

            return {
                "success": True,
                "answer": answer,
                "provider": "Gemini",
                "model": model
            }

        except Exception as error:

            errors.append(f"{model}: {error}")

            record_provider_usage(
                "Gemini",
                model,
                workspace,
                False,
                user_id
            )

            logger.exception(
                "Gemini model %s failed.",
                model
            )

    raise RuntimeError(
        "All configured Gemini models failed. "
        + " | ".join(errors)
    )


# ============================================================
# 7. DEEP RESEARCH MODEL ROUTER
# ============================================================

def generate_research_ai_response(
    prompt,
    history=None,
    user_id=None,
    system_instruction=None
):

    prompt = safe_text(prompt, MAX_DOCUMENT_CHARS)

    if not prompt:
        raise ValueError("Research prompt cannot be empty.")

    models = [
        RESEARCH_PRIMARY_MODEL,
        RESEARCH_FALLBACK_MODEL
    ]

    errors = []

    for model in models:

        try:

            answer = call_gemini(
                prompt=prompt,
                history=history,
                model=model,
                system_instruction=system_instruction
            )

            record_provider_usage(
                "Gemini",
                model,
                "Deep Research",
                True,
                user_id
            )

            return {
                "success": True,
                "answer": answer,
                "provider": "Gemini",
                "model": model
            }

        except Exception as error:

            errors.append(f"{model}: {error}")

            record_provider_usage(
                "Gemini",
                model,
                "Deep Research",
                False,
                user_id
            )

            logger.exception(
                "Research Gemini model failed."
            )

    # OpenRouter is optional and research-only.
    if (
        OPENROUTER_API_KEY
        and is_approved_free_model(
            OPENROUTER_RESEARCH_MODEL
        )
    ):

        try:

            answer = call_openrouter(
                prompt=prompt,
                history=history,
                model=OPENROUTER_RESEARCH_MODEL,
                system_instruction=system_instruction
            )

            record_provider_usage(
                "OpenRouter",
                OPENROUTER_RESEARCH_MODEL,
                "Deep Research",
                True,
                user_id
            )

            return {
                "success": True,
                "answer": answer,
                "provider": "OpenRouter",
                "model": OPENROUTER_RESEARCH_MODEL
            }

        except Exception as error:

            errors.append(f"OpenRouter: {error}")

            record_provider_usage(
                "OpenRouter",
                OPENROUTER_RESEARCH_MODEL,
                "Deep Research",
                False,
                user_id
            )

            logger.exception(
                "OpenRouter research request failed."
            )

    raise RuntimeError(
        "All configured research providers failed. "
        + " | ".join(errors)
    )


# ============================================================
# 8. AI HEALTH CHECK
# ============================================================

def get_ai_provider_status():

    return {
        "Gemini configured": bool(GEMINI_API_KEY),
        "OpenRouter configured": bool(OPENROUTER_API_KEY),
        "OpenRouter research model approved": (
            is_approved_free_model(
                OPENROUTER_RESEARCH_MODEL
            )
        ),
        "General primary model": PRIMARY_MODEL,
        "General fallback model": FALLBACK_MODEL,
        "Research primary model": RESEARCH_PRIMARY_MODEL,
        "Research fallback model": RESEARCH_FALLBACK_MODEL
    }


# ============================================================
# END OF BLOCK 3
# ============================================================

# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 4 OF 6
# CHAT HISTORY, SAVED ITEMS, LIBRARY AND WORKSPACES
# ============================================================

# ============================================================
# 1. AUTHENTICATED USER HELPER
# ============================================================

def get_current_user_id():

    user = st.session_state.get("auth_user")

    if not isinstance(user, dict):
        return None

    return user.get("id")


def require_user_id():

    user_id = get_current_user_id()

    if not user_id:
        raise PermissionError(
            "Please sign in to continue."
        )

    return str(user_id)


# ============================================================
# 2. CONVERSATION MANAGEMENT
# ============================================================

def create_conversation(title="New conversation"):

    user_id = require_user_id()
    conversation_id = new_id()

    execute_sql(
        """
        INSERT INTO conversations (
            id, user_id, title, is_archived,
            created_at, updated_at
        )
        VALUES (
            :id, :user_id, :title, FALSE, NOW(), NOW()
        )
        """,
        {
            "id": conversation_id,
            "user_id": user_id,
            "title": safe_text(title, 300)
        }
    )

    st.session_state["conversation_id"] = conversation_id

    return conversation_id


def get_conversations(limit=100, include_archived=False):

    user_id = require_user_id()

    limit = max(1, min(int(limit), 200))

    return execute_sql(
        """
        SELECT
            id, title, is_archived,
            created_at, updated_at
        FROM conversations
        WHERE user_id = :user_id
          AND (
              :include_archived = TRUE
              OR is_archived = FALSE
          )
        ORDER BY updated_at DESC
        LIMIT :limit
        """,
        {
            "user_id": user_id,
            "include_archived": bool(include_archived),
            "limit": limit
        },
        fetch=True
    )


def get_conversation(conversation_id):

    user_id = require_user_id()

    rows = execute_sql(
        """
        SELECT *
        FROM conversations
        WHERE id = :id
          AND user_id = :user_id
        LIMIT 1
        """,
        {
            "id": str(conversation_id),
            "user_id": user_id
        },
        fetch=True
    )

    return rows[0] if rows else None


def rename_conversation(conversation_id, title):

    user_id = require_user_id()

    return execute_sql(
        """
        UPDATE conversations
        SET title = :title,
            updated_at = NOW()
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(conversation_id),
            "user_id": user_id,
            "title": safe_text(title, 300)
        }
    ) > 0


def archive_conversation(conversation_id):

    user_id = require_user_id()

    return execute_sql(
        """
        UPDATE conversations
        SET is_archived = TRUE,
            updated_at = NOW()
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(conversation_id),
            "user_id": user_id
        }
    ) > 0


def delete_conversation(conversation_id):

    user_id = require_user_id()

    deleted = execute_sql(
        """
        DELETE FROM conversations
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(conversation_id),
            "user_id": user_id
        }
    )

    if (
        st.session_state.get("conversation_id")
        == str(conversation_id)
    ):
        st.session_state["conversation_id"] = None

    return deleted > 0


# ============================================================
# 3. MESSAGE MANAGEMENT
# ============================================================

def save_message(
    conversation_id,
    role,
    content
):

    user_id = require_user_id()

    role = str(role).lower().strip()

    if role not in ["user", "assistant", "system"]:
        raise ValueError("Invalid message role.")

    conversation = get_conversation(conversation_id)

    if not conversation:
        raise PermissionError(
            "Conversation not found or access denied."
        )

    content = safe_text(content, MAX_DOCUMENT_CHARS)

    if not content:
        raise ValueError("Message content cannot be empty.")

    message_id = new_id()

    execute_sql(
        """
        INSERT INTO messages (
            id, conversation_id, user_id,
            role, content, created_at
        )
        VALUES (
            :id, :conversation_id, :user_id,
            :role, :content, NOW()
        )
        """,
        {
            "id": message_id,
            "conversation_id": str(conversation_id),
            "user_id": user_id,
            "role": role,
            "content": content
        }
    )

    execute_sql(
        """
        UPDATE conversations
        SET updated_at = NOW()
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(conversation_id),
            "user_id": user_id
        }
    )

    return message_id


def get_messages(conversation_id, limit=100):

    user_id = require_user_id()

    conversation = get_conversation(conversation_id)

    if not conversation:
        raise PermissionError(
            "Conversation not found or access denied."
        )

    limit = max(1, min(int(limit), 300))

    return execute_sql(
        """
        SELECT id, role, content, created_at
        FROM messages
        WHERE conversation_id = :conversation_id
          AND user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {
            "conversation_id": str(conversation_id),
            "user_id": user_id,
            "limit": limit
        },
        fetch=True
    )[::-1]


def get_ai_history(conversation_id, limit=20):

    messages = get_messages(
        conversation_id,
        limit=limit
    )

    return [
        {
            "role": item["role"],
            "content": item["content"]
        }
        for item in messages
        if item["role"] in ["user", "assistant"]
    ]


def generate_conversation_title(first_message):

    title = safe_text(first_message, 80)

    if not title:
        return "New conversation"

    return title[:77] + "..." if len(title) > 80 else title


# ============================================================
# 4. SAVED ITEMS
# ============================================================

def save_item(
    title,
    content,
    item_type="general"
):

    user_id = require_user_id()

    item_id = new_id()

    execute_sql(
        """
        INSERT INTO saved_items (
            id, user_id, title,
            content, item_type, created_at
        )
        VALUES (
            :id, :user_id, :title,
            :content, :item_type, NOW()
        )
        """,
        {
            "id": item_id,
            "user_id": user_id,
            "title": safe_text(title, 300),
            "content": safe_text(content, MAX_DOCUMENT_CHARS),
            "item_type": safe_text(item_type, 50)
        }
    )

    return item_id


def get_saved_items(limit=100):

    user_id = require_user_id()

    limit = max(1, min(int(limit), 200))

    return execute_sql(
        """
        SELECT *
        FROM saved_items
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {
            "user_id": user_id,
            "limit": limit
        },
        fetch=True
    )


def delete_saved_item(item_id):

    user_id = require_user_id()

    return execute_sql(
        """
        DELETE FROM saved_items
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(item_id),
            "user_id": user_id
        }
    ) > 0


# ============================================================
# 5. LIBRARY FILE RECORDS
# ============================================================

def save_library_file(
    filename,
    storage_path,
    file_type=None,
    file_size=0,
    extracted_text=""
):

    user_id = require_user_id()

    file_id = new_id()

    execute_sql(
        """
        INSERT INTO library_files (
            id, user_id, filename, storage_path,
            file_type, file_size, extracted_text,
            created_at
        )
        VALUES (
            :id, :user_id, :filename, :storage_path,
            :file_type, :file_size, :extracted_text,
            NOW()
        )
        """,
        {
            "id": file_id,
            "user_id": user_id,
            "filename": safe_text(filename, 500),
            "storage_path": safe_text(storage_path, 2000),
            "file_type": safe_text(file_type, 100),
            "file_size": max(0, int(file_size)),
            "extracted_text": safe_text(
                extracted_text,
                MAX_DOCUMENT_CHARS
            )
        }
    )

    return file_id


def get_library_files(limit=100):

    user_id = require_user_id()

    limit = max(1, min(int(limit), 200))

    return execute_sql(
        """
        SELECT
            id, filename, file_type,
            file_size, created_at
        FROM library_files
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {
            "user_id": user_id,
            "limit": limit
        },
        fetch=True
    )


def get_library_file(file_id):

    user_id = require_user_id()

    rows = execute_sql(
        """
        SELECT *
        FROM library_files
        WHERE id = :id
          AND user_id = :user_id
        LIMIT 1
        """,
        {
            "id": str(file_id),
            "user_id": user_id
        },
        fetch=True
    )

    return rows[0] if rows else None


def delete_library_file(file_id):

    user_id = require_user_id()

    file_record = get_library_file(file_id)

    if not file_record:
        return False

    storage_path = file_record.get("storage_path")

    execute_sql(
        """
        DELETE FROM library_files
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(file_id),
            "user_id": user_id
        }
    )

    # Delete only files inside the application's
    # configured local storage directory.
    if storage_path:

        try:

            base = Path("vinci_storage").resolve()
            target = Path(storage_path).resolve()

            if base in target.parents and target.is_file():
                target.unlink()

        except Exception:

            logger.exception(
                "Library file cleanup failed."
            )

    return True


# ============================================================
# 6. REMINDERS AND SCHEDULE
# ============================================================

def create_reminder(
    title,
    reminder_time,
    description=""
):

    user_id = require_user_id()

    if isinstance(reminder_time, str):

        reminder_time = datetime.fromisoformat(
            reminder_time.replace("Z", "+00:00")
        )

    if reminder_time.tzinfo is None:

        reminder_time = reminder_time.replace(
            tzinfo=timezone.utc
        )

    reminder_id = new_id()

    execute_sql(
        """
        INSERT INTO reminders (
            id, user_id, title, description,
            reminder_time, is_completed, created_at
        )
        VALUES (
            :id, :user_id, :title, :description,
            :reminder_time, FALSE, NOW()
        )
        """,
        {
            "id": reminder_id,
            "user_id": user_id,
            "title": safe_text(title, 300),
            "description": safe_text(description, 5000),
            "reminder_time": reminder_time
        }
    )

    return reminder_id


def get_reminders(limit=100):

    user_id = require_user_id()

    limit = max(1, min(int(limit), 200))

    return execute_sql(
        """
        SELECT *
        FROM reminders
        WHERE user_id = :user_id
        ORDER BY reminder_time ASC
        LIMIT :limit
        """,
        {
            "user_id": user_id,
            "limit": limit
        },
        fetch=True
    )


def complete_reminder(reminder_id):

    user_id = require_user_id()

    return execute_sql(
        """
        UPDATE reminders
        SET is_completed = TRUE
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(reminder_id),
            "user_id": user_id
        }
    ) > 0


def delete_reminder(reminder_id):

    user_id = require_user_id()

    return execute_sql(
        """
        DELETE FROM reminders
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": str(reminder_id),
            "user_id": user_id
        }
    ) > 0


# ============================================================
# 7. WORKSPACE SESSION PERSISTENCE
# ============================================================

def save_workspace_session(workspace, session_data):

    user_id = require_user_id()

    workspace = safe_text(workspace, 100)

    if not workspace:
        raise ValueError("Workspace name is required.")

    if not isinstance(session_data, dict):
        raise ValueError("Workspace data must be a dictionary.")

    serialized = json.dumps(
        session_data,
        ensure_ascii=False,
        default=str
    )

    execute_sql(
        """
        INSERT INTO workspace_sessions (
            id, user_id, workspace,
            session_data, updated_at
        )
        VALUES (
            :id, :user_id, :workspace,
            CAST(:session_data AS JSONB), NOW()
        )
        ON CONFLICT (user_id, workspace)
        DO UPDATE SET
            session_data = EXCLUDED.session_data,
            updated_at = NOW()
        """,
        {
            "id": new_id(),
            "user_id": user_id,
            "workspace": workspace,
            "session_data": serialized
        }
    )

    st.session_state.setdefault(
        "workspace_sessions", {}
    )[workspace] = session_data

    return True


def load_workspace_session(workspace):

    user_id = require_user_id()

    rows = execute_sql(
        """
        SELECT session_data
        FROM workspace_sessions
        WHERE user_id = :user_id
          AND workspace = :workspace
        LIMIT 1
        """,
        {
            "user_id": user_id,
            "workspace": safe_text(workspace, 100)
        },
        fetch=True
    )

    if not rows:
        return {}

    data = rows[0]["session_data"]

    if isinstance(data, str):

        try:
            data = json.loads(data)

        except Exception:
            data = {}

    if not isinstance(data, dict):
        data = {}

    st.session_state.setdefault(
        "workspace_sessions", {}
    )[workspace] = data

    return data


# ============================================================
# 8. ADMIN ACTIVITY LOGGING
# ============================================================

def record_admin_activity(action, details=""):

    user_id = get_current_user_id()

    execute_sql(
        """
        INSERT INTO admin_activity_logs (
            id, user_id, action, details, created_at
        )
        VALUES (
            :id, :user_id, :action, :details, NOW()
        )
        """,
        {
            "id": new_id(),
            "user_id": str(user_id) if user_id else None,
            "action": safe_text(action, 200),
            "details": safe_text(details, 5000)
        }
    )

    return True


# ============================================================
# 9. ADMIN USER MANAGEMENT
# ============================================================

def admin_update_user_status(user_id, is_active):

    if not current_user_is_admin():
        raise PermissionError("Administrator access required.")

    result = execute_sql(
        """
        UPDATE users
        SET is_active = :is_active,
            updated_at = NOW()
        WHERE id = :user_id
        """,
        {
            "user_id": str(user_id),
            "is_active": bool(is_active)
        }
    )

    if result:

        if not is_active:

            execute_sql(
                """
                UPDATE sessions
                SET revoked = TRUE
                WHERE user_id = :user_id
                """,
                {"user_id": str(user_id)}
            )

        record_admin_activity(
            "user_status_changed",
            f"User {user_id}; active={bool(is_active)}"
        )

    return result > 0


def get_admin_recent_activity(limit=100):

    if not current_user_is_admin():
        raise PermissionError("Administrator access required.")

    limit = max(1, min(int(limit), 200))

    return execute_sql(
        """
        SELECT
            id, user_id, action,
            details, created_at
        FROM admin_activity_logs
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
        fetch=True
    )


# ============================================================
# END OF BLOCK 4
# ============================================================

# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 5 OF 6
# DEEP RESEARCH, IMAGE STUDIO, DOCUMENTS AND VOICE
# ============================================================

import csv
import tempfile


# ============================================================
# 1. STORAGE CONFIGURATION
# ============================================================

STORAGE_DIRECTORY = Path("vinci_storage")

STORAGE_DIRECTORY.mkdir(
    parents=True,
    exist_ok=True
)

MAX_AUDIO_MB = 20
MAX_IMAGE_MB = 15


def save_uploaded_file(uploaded_file, user_id):

    if uploaded_file is None:
        raise ValueError("No file was supplied.")

    file_bytes = uploaded_file.getvalue()

    if len(file_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError("File exceeds the upload limit.")

    user_directory = (
        STORAGE_DIRECTORY / str(user_id)
    ).resolve()

    user_directory.mkdir(
        parents=True,
        exist_ok=True
    )

    original_name = Path(
        uploaded_file.name
    ).name

    extension = Path(original_name).suffix.lower()

    if not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
        extension = ""

    stored_name = f"{new_id()}{extension}"

    destination = (
        user_directory / stored_name
    ).resolve()

    if user_directory not in destination.parents:
        raise ValueError("Invalid storage path.")

    destination.write_bytes(file_bytes)

    return {
        "path": str(destination),
        "filename": original_name,
        "size": len(file_bytes),
        "type": uploaded_file.type or "application/octet-stream"
    }


# ============================================================
# 2. DOCUMENT TEXT EXTRACTION
# ============================================================

def extract_document_text(file_bytes, filename):

    extension = Path(filename).suffix.lower()

    if extension == ".txt":

        return file_bytes.decode(
            "utf-8",
            errors="replace"
        )[:MAX_DOCUMENT_CHARS]

    if extension == ".csv":

        text_content = file_bytes.decode(
            "utf-8",
            errors="replace"
        )

        return text_content[:MAX_DOCUMENT_CHARS]

    if extension == ".pdf":

        try:

            from pypdf import PdfReader

            reader = PdfReader(
                io.BytesIO(file_bytes)
            )

            extracted = []

            for page in reader.pages[:100]:

                extracted.append(
                    page.extract_text() or ""
                )

            return "\n".join(
                extracted
            )[:MAX_DOCUMENT_CHARS]

        except Exception as error:

            raise RuntimeError(
                f"PDF extraction failed: {error}"
            )

    if extension == ".docx":

        try:

            from docx import Document

            document = Document(
                io.BytesIO(file_bytes)
            )

            paragraphs = [
                paragraph.text
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            ]

            return "\n".join(
                paragraphs
            )[:MAX_DOCUMENT_CHARS]

        except Exception as error:

            raise RuntimeError(
                f"DOCX extraction failed: {error}"
            )

    if extension == ".xlsx":

        try:

            from openpyxl import load_workbook

            workbook = load_workbook(
                io.BytesIO(file_bytes),
                read_only=True,
                data_only=True
            )

            extracted = []

            for sheet in workbook.worksheets:

                extracted.append(
                    f"WORKSHEET: {sheet.title}"
                )

                for row in sheet.iter_rows(
                    max_row=500,
                    values_only=True
                ):

                    values = [
                        str(value)
                        for value in row
                        if value is not None
                    ]

                    if values:
                        extracted.append(
                            " | ".join(values)
                        )

            workbook.close()

            return "\n".join(
                extracted
            )[:MAX_DOCUMENT_CHARS]

        except Exception as error:

            raise RuntimeError(
                f"Excel extraction failed: {error}"
            )

    if extension in [".png", ".jpg", ".jpeg", ".webp"]:

        try:

            from PIL import Image
            import pytesseract

            image = Image.open(
                io.BytesIO(file_bytes)
            )

            return pytesseract.image_to_string(
                image
            )[:MAX_DOCUMENT_CHARS]

        except Exception:

            return (
                "Image uploaded. Text extraction is unavailable. "
                "Use VINCI AI image analysis."
            )

    raise ValueError(
        "Unsupported document format. "
        "Supported formats: PDF, DOCX, XLSX, CSV, TXT and images."
    )


# ============================================================
# 3. DOCUMENT UPLOAD AND LIBRARY REGISTRATION
# ============================================================

def process_library_upload(uploaded_file):

    user_id = require_user_id()

    stored = save_uploaded_file(
        uploaded_file,
        user_id
    )

    extracted = ""

    try:

        extracted = extract_document_text(
            uploaded_file.getvalue(),
            uploaded_file.name
        )

    except Exception:

        logger.exception(
            "Document extraction failed."
        )

    file_id = save_library_file(
        filename=stored["filename"],
        storage_path=stored["path"],
        file_type=stored["type"],
        file_size=stored["size"],
        extracted_text=extracted
    )

    return {
        "id": file_id,
        "filename": stored["filename"],
        "size": stored["size"],
        "type": stored["type"],
        "extracted_text": extracted
    }


# ============================================================
# 4. DOCUMENT ANALYSIS
# ============================================================

def analyze_document(
    document_text,
    question,
    user_id=None
):

    document_text = safe_text(
        document_text,
        MAX_DOCUMENT_CHARS
    )

    question = safe_text(question, 10000)

    if not document_text:
        raise ValueError("No document text is available.")

    prompt = f"""
Analyze the following document carefully.

USER'S QUESTION:
{question or "Provide a comprehensive summary."}

DOCUMENT:
{document_text}

Instructions:
1. Use only information supported by the document.
2. Distinguish facts from interpretations.
3. Identify important sections and findings.
4. Explain technical terms where necessary.
5. Mention missing or unclear information.
6. Do not invent information.
"""

    return generate_ai_response(
        prompt=prompt,
        workspace="Document Analysis",
        user_id=user_id
    )


# ============================================================
# 5. DEEP RESEARCH
# ============================================================

def run_deep_research(
    research_question,
    source_material="",
    user_id=None
):

    research_question = safe_text(
        research_question,
        10000
    )

    source_material = safe_text(
        source_material,
        MAX_DOCUMENT_CHARS
    )

    if not research_question:
        raise ValueError(
            "Enter a research question."
        )

    research_prompt = f"""
You are VINCI AI's Deep Research analyst.

RESEARCH QUESTION:
{research_question}

USER-PROVIDED SOURCE MATERIAL:
{source_material or "No source material supplied."}

Produce a professional research report.

Use this structure:

1. Executive Summary
2. Background and Context
3. Main Findings
4. Technical or Scientific Explanation
5. Opportunities
6. Challenges and Limitations
7. Practical Recommendations
8. Conclusion
9. Further Research Questions

IMPORTANT:
- Never invent citations or claim to have searched the internet.
- Identify which conclusions are based on supplied material.
- Clearly distinguish established facts from estimates.
- Explain uncertainty.
- Use tables where useful.
- Be comprehensive and analytical.
"""

    result = generate_research_ai_response(
        prompt=research_prompt,
        user_id=user_id,
        system_instruction=AI_SYSTEM_INSTRUCTION
    )

    st.session_state["research_result"] = result

    return result


# ============================================================
# 6. IMAGE ANALYSIS
# ============================================================

def analyze_uploaded_image(
    image_bytes,
    mime_type,
    question="Describe and analyze this image."
):

    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini API key is missing.")

    if len(image_bytes) > MAX_IMAGE_MB * 1024 * 1024:
        raise ValueError("Image is too large.")

    allowed_types = [
        "image/png",
        "image/jpeg",
        "image/webp"
    ]

    if mime_type not in allowed_types:
        raise ValueError("Unsupported image format.")

    selected_model = PRIMARY_MODEL

    url = (
        f"{GEMINI_API_BASE}/{selected_model}:generateContent"
    )

    payload = {
        "systemInstruction": {
            "parts": [{
                "text": AI_SYSTEM_INSTRUCTION
            }]
        },
        "contents": [{
            "role": "user",
            "parts": [
                {
                    "text": safe_text(question, 10000)
                },
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(
                            image_bytes
                        ).decode("utf-8")
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 4096
        }
    }

    response = httpx.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=AI_REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Image analysis failed: "
            f"{response.status_code} "
            f"{response.text[:500]}"
        )

    data = response.json()

    parts = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )

    answer = "\n".join(
        part.get("text", "")
        for part in parts
        if part.get("text")
    ).strip()

    if not answer:
        raise RuntimeError(
            "No image analysis was returned."
        )

    record_provider_usage(
        "Gemini",
        selected_model,
        "Image Studio",
        True,
        get_current_user_id()
    )

    return answer


# ============================================================
# 7. IMAGE GENERATION
# ============================================================

def generate_image(prompt, user_id=None):

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OpenRouter API key is missing."
        )

    model = OPENROUTER_IMAGE_MODEL

    if not is_approved_free_model(model):

        raise RuntimeError(
            "Image generation requires an approved "
            "OpenRouter model ending in :free. "
            "No paid model will be used."
        )

    prompt = safe_text(prompt, 10000)

    if not prompt:
        raise ValueError("Image prompt is empty.")

    response = httpx.post(
        f"{OPENROUTER_API_BASE}/images/generations",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://vinci-ai.streamlit.app",
            "X-Title": "VINCI AI Image Studio"
        },
        json={
            "model": model,
            "prompt": prompt,
            "n": 1
        },
        timeout=120
    )

    if response.status_code != 200:

        raise RuntimeError(
            "Image provider failed or does not support "
            "image generation through this endpoint. "
            f"HTTP {response.status_code}: "
            f"{response.text[:700]}"
        )

    data = response.json()

    image_items = data.get("data", [])

    if not image_items:
        raise RuntimeError(
            "The image provider returned no image."
        )

    image_url = image_items[0].get("url")

    if not image_url:
        raise RuntimeError(
            "The provider did not return a downloadable image URL."
        )

    # Download only from HTTPS.
    if not image_url.startswith("https://"):
        raise RuntimeError("Invalid image URL.")

    image_response = httpx.get(
        image_url,
        timeout=60,
        follow_redirects=False
    )

    if image_response.status_code != 200:
        raise RuntimeError("Generated image download failed.")

    image_bytes = image_response.content

    if len(image_bytes) > MAX_IMAGE_MB * 1024 * 1024:
        raise RuntimeError("Generated image exceeds the size limit.")

    from PIL import Image

    image = Image.open(
        io.BytesIO(image_bytes)
    )

    image.load()

    user_id = str(user_id or require_user_id())

    user_directory = (
        STORAGE_DIRECTORY / user_id
    ).resolve()

    user_directory.mkdir(
        parents=True,
        exist_ok=True
    )

    image_id = new_id()

    image_path = (
        user_directory / f"{image_id}.png"
    ).resolve()

    if user_directory not in image_path.parents:
        raise RuntimeError("Invalid image storage path.")

    image.convert("RGB").save(
        image_path,
        format="PNG"
    )

    execute_sql(
        """
        INSERT INTO generated_images (
            id, user_id, prompt,
            storage_path, model, created_at
        )
        VALUES (
            :id, :user_id, :prompt,
            :storage_path, :model, NOW()
        )
        """,
        {
            "id": image_id,
            "user_id": user_id,
            "prompt": prompt,
            "storage_path": str(image_path),
            "model": model
        }
    )

    record_provider_usage(
        "OpenRouter",
        model,
        "Image Studio",
        True,
        user_id
    )

    return {
        "id": image_id,
        "path": str(image_path),
        "prompt": prompt,
        "model": model
    }


# ============================================================
# 8. AUDIO TRANSCRIPTION
# ============================================================

def transcribe_audio(audio_bytes, mime_type):

    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini API key is missing.")

    if len(audio_bytes) > MAX_AUDIO_MB * 1024 * 1024:
        raise ValueError("Audio file is too large.")

    allowed_types = [
        "audio/wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/aac",
        "audio/ogg",
        "audio/webm",
        "audio/flac"
    ]

    if mime_type not in allowed_types:
        raise ValueError("Unsupported audio format.")

    model = PRIMARY_MODEL

    url = (
        f"{GEMINI_API_BASE}/{model}:generateContent"
    )

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {
                    "text": (
                        "Transcribe this audio accurately. "
                        "Return only the spoken words. "
                        "Preserve the original language."
                    )
                },
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(
                            audio_bytes
                        ).decode("utf-8")
                    }
                }
            ]
        }]
    }

    response = httpx.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=AI_REQUEST_TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Audio transcription failed: "
            f"{response.status_code} "
            f"{response.text[:500]}"
        )

    data = response.json()

    parts = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )

    transcription = "\n".join(
        part.get("text", "")
        for part in parts
        if part.get("text")
    ).strip()

    if not transcription:
        raise RuntimeError(
            "No transcription was returned."
        )

    record_provider_usage(
        "Gemini",
        model,
        "Voice",
        True,
        get_current_user_id()
    )

    return transcription


# ============================================================
# 9. USER IMAGE HISTORY
# ============================================================

def get_generated_images(limit=50):

    user_id = require_user_id()

    limit = max(1, min(int(limit), 100))

    return execute_sql(
        """
        SELECT id, prompt, storage_path, model, created_at
        FROM generated_images
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {
            "user_id": user_id,
            "limit": limit
        },
        fetch=True
    )


# ============================================================
# END OF BLOCK 5
# ============================================================

# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 6 OF 6
# COMPLETE APPLICATION INTERFACE
# ============================================================


# ============================================================
# 1. UI CONFIGURATION
# ============================================================

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(
            135deg,
            #081526 0%,
            #101d35 55%,
            #17233e 100%
        );
    }

    h1, h2, h3, p, label {
        color: #f4f7ff;
    }

    .vinci-header {
        padding: 22px;
        border-radius: 18px;
        background: linear-gradient(
            120deg,
            #123b67,
            #252a59
        );
        border: 1px solid #355b91;
        margin-bottom: 20px;
    }

    .vinci-card {
        padding: 20px;
        border-radius: 16px;
        background: rgba(31, 48, 78, 0.88);
        border: 1px solid #344f75;
        min-height: 120px;
        margin-bottom: 12px;
    }

    .vinci-muted {
        color: #aab9d2;
    }

    .stButton button {
        border-radius: 10px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


def vinci_header():

    st.markdown("""
    <div class="vinci-header">
        <h1>⚡ VINCI AI</h1>
        <p>JTEG INTELLIGENCE PLATFORM</p>
        <p class="vinci-muted">
            Engineering intelligence. Research.
            Creativity. Productivity.
        </p>
    </div>
    """, unsafe_allow_html=True)


def workspace_card(title, description, icon, key):

    st.markdown(
        f"""
        <div class="vinci-card">
            <h3>{icon} {title}</h3>
            <p class="vinci-muted">{description}</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.button(
        f"Open {title}",
        key=f"open_{key}",
        use_container_width=True
    ):

        st.session_state["page"] = title

        st.rerun()


# ============================================================
# 2. SESSION RESTORATION
# ============================================================

if not st.session_state.get("authenticated"):

    try:
        restore_authenticated_session()

    except Exception:
        logger.exception("Session restoration failed.")


# ============================================================
# 3. AUTHENTICATION INTERFACE
# ============================================================

def render_authentication():

    vinci_header()

    login_tab, register_tab, verify_tab = st.tabs([
        "Sign In",
        "Create Account",
        "Verify Email"
    ])

    with login_tab:

        st.subheader("Welcome back")

        with st.form("vinci_login_form"):

            email = st.text_input(
                "Email address"
            )

            password = st.text_input(
                "Password",
                type="password"
            )

            submitted = st.form_submit_button(
                "Sign In",
                use_container_width=True
            )

        if submitted:

            try:

                success = authenticate_user(
                    email,
                    password
                )

                if success:

                    st.success("Login successful.")

                    st.session_state["page"] = "Chat"

                    st.rerun()

                else:

                    st.error(
                        "Login failed. Check your details, "
                        "account verification and account status."
                    )

            except Exception as error:

                logger.exception("Login failed.")

                st.error(str(error))

    with register_tab:

        st.subheader("Create your VINCI account")

        with st.form("vinci_registration_form"):

            full_name = st.text_input("Full name")

            reg_email = st.text_input("Email address")

            phone = st.text_input("Phone number")

            job = st.text_area(
                "Job description"
            )

            reg_password = st.text_input(
                "Password",
                type="password"
            )

            confirm_password = st.text_input(
                "Confirm password",
                type="password"
            )

            submitted = st.form_submit_button(
                "Create Account",
                use_container_width=True
            )

        if submitted:

            try:

                if reg_password != confirm_password:

                    raise ValueError(
                        "Passwords do not match."
                    )

                register_user(
                    full_name,
                    reg_email,
                    phone,
                    job,
                    reg_password
                )

                st.success(
                    "Registration successful. "
                    "Check your email for your verification code."
                )

                st.session_state["pending_email"] = (
                    normalize_email(reg_email)
                )

            except Exception as error:

                logger.exception("Registration failed.")

                st.error(str(error))

    with verify_tab:

        st.subheader("Verify your email")

        verification_email = st.text_input(
            "Registered email",
            value=st.session_state.get(
                "pending_email"
            ) or "",
            key="verification_email_input"
        )

        verification_code = st.text_input(
            "Six-digit verification code",
            max_chars=6
        )

        if st.button(
            "Verify Account",
            use_container_width=True
        ):

            try:

                verified = verify_registration_code(
                    verification_email,
                    verification_code
                )

                if verified:

                    st.success(
                        "Email verified. You can now sign in."
                    )

                else:

                    st.error(
                        "Verification failed. "
                        "Check the code or request another."
                    )

            except Exception as error:

                st.error(str(error))

        if st.button(
            "Resend Verification Code",
            use_container_width=True
        ):

            try:

                resend_verification_code(
                    verification_email
                )

                st.success(
                    "A new verification code has been sent."
                )

            except Exception as error:

                st.error(str(error))


# ============================================================
# 4. CHAT WORKSPACE
# ============================================================

def render_chat():

    st.title("💬 Chat with VINCI")

    user_id = require_user_id()

    conversations = get_conversations()

    col1, col2 = st.columns([1, 3])

    with col1:

        if st.button(
            "＋ New Chat",
            use_container_width=True
        ):

            create_conversation()

            st.rerun()

        st.subheader("Recent chats")

        for conversation in conversations:

            if st.button(
                conversation["title"][:35],
                key=f"conversation_{conversation['id']}",
                use_container_width=True
            ):

                st.session_state["conversation_id"] = (
                    conversation["id"]
                )

                st.rerun()

    with col2:

        conversation_id = st.session_state.get(
            "conversation_id"
        )

        if conversation_id and not get_conversation(
            conversation_id
        ):

            conversation_id = None

            st.session_state["conversation_id"] = None

        if not conversation_id:

            conversation_id = create_conversation()

        messages = get_messages(
            conversation_id,
            limit=100
        )

        for message in messages:

            with st.chat_message(message["role"]):

                st.markdown(message["content"])

        uploaded_image = st.file_uploader(
            "Attach an image",
            type=["png", "jpg", "jpeg", "webp"],
            key="chat_image_upload"
        )

        uploaded_document = st.file_uploader(
            "Attach a document",
            type=["pdf", "docx", "txt", "csv", "xlsx"],
            key="chat_document_upload"
        )

        if uploaded_document:

            try:

                extracted = extract_document_text(
                    uploaded_document.getvalue(),
                    uploaded_document.name
                )

                st.session_state["document_context"] = (
                    extracted
                )

                st.session_state[
                    "chat_uploaded_document_name"
                ] = uploaded_document.name

                st.success(
                    f"Document loaded: {uploaded_document.name}"
                )

            except Exception as error:

                st.error(str(error))

        if uploaded_image:

            st.session_state["chat_image"] = (
                uploaded_image.getvalue()
            )

            st.session_state["chat_image_mime"] = (
                uploaded_image.type
            )

        prompt = st.chat_input(
            "Ask VINCI anything..."
        )

        if prompt:

            try:

                save_message(
                    conversation_id,
                    "user",
                    prompt
                )

                if len(messages) == 0:

                    rename_conversation(
                        conversation_id,
                        generate_conversation_title(prompt)
                    )

                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):

                    with st.spinner(
                        "VINCI is thinking..."
                    ):

                        image_bytes = st.session_state.get(
                            "chat_image"
                        )

                        if image_bytes:

                            answer = analyze_uploaded_image(
                                image_bytes,
                                st.session_state.get(
                                    "chat_image_mime"
                                ) or "image/jpeg",
                                prompt
                            )

                            result = {
                                "answer": answer
                            }

                        else:

                            context = st.session_state.get(
                                "document_context",
                                ""
                            )

                            complete_prompt = prompt

                            if context:

                                complete_prompt = (
                                    "DOCUMENT CONTEXT:\n"
                                    + context
                                    + "\n\nUSER QUESTION:\n"
                                    + prompt
                                )

                            history = get_ai_history(
                                conversation_id,
                                limit=20
                            )

                            result = generate_ai_response(
                                prompt=complete_prompt,
                                history=history[:-1],
                                workspace="Chat",
                                user_id=user_id
                            )

                            answer = result["answer"]

                        st.markdown(answer)

                save_message(
                    conversation_id,
                    "assistant",
                    answer
                )

                st.session_state["chat_image"] = None
                st.session_state["chat_image_mime"] = None

                st.rerun()

            except Exception as error:

                logger.exception("Chat request failed.")

                st.error(
                    f"VINCI could not complete your request: {error}"
                )


# ============================================================
# 5. DEEP RESEARCH WORKSPACE
# ============================================================

def render_deep_research():

    st.title("🔬 Deep Research")

    st.write(
        "Conduct structured AI-assisted research and "
        "produce professional research reports."
    )

    question = st.text_area(
        "What would you like VINCI to research?",
        height=130
    )

    sources = st.text_area(
        "Optional source material or notes",
        height=160
    )

    if st.button(
        "Start Deep Research",
        use_container_width=True
    ):

        try:

            with st.spinner(
                "VINCI is analyzing your research question..."
            ):

                result = run_deep_research(
                    question,
                    sources,
                    require_user_id()
                )

            st.session_state["research_result"] = result

        except Exception as error:

            logger.exception("Research failed.")

            st.error(str(error))

    result = st.session_state.get(
        "research_result"
    )

    if result:

        st.divider()

        st.subheader("Research Report")

        st.markdown(result["answer"])

        st.caption(
            f"Provider: {result['provider']} | "
            f"Model: {result['model']}"
        )

        if st.button("Save Research Report"):

            save_item(
                "Deep Research Report",
                result["answer"],
                "research"
            )

            st.success("Report saved.")


# ============================================================
# 6. IMAGE STUDIO
# ============================================================

def render_image_studio():

    st.title("🎨 Image Studio")

    mode = st.radio(
        "Choose an operation",
        [
            "Generate Image",
            "Analyze Image"
        ],
        horizontal=True
    )

    if mode == "Generate Image":

        prompt = st.text_area(
            "Describe the image you want to create",
            height=140
        )

        st.info(
            "Image generation requires an approved free "
            "OpenRouter image model in your private secrets."
        )

        if st.button(
            "Generate Image",
            use_container_width=True
        ):

            try:

                with st.spinner("Creating image..."):

                    result = generate_image(
                        prompt,
                        require_user_id()
                    )

                st.session_state["image_result"] = result

                st.success("Image generated.")

            except Exception as error:

                logger.exception("Image generation failed.")

                st.error(str(error))

        result = st.session_state.get(
            "image_result"
        )

        if result and Path(result["path"]).is_file():

            st.image(
                result["path"],
                caption=result["prompt"],
                use_container_width=True
            )

    else:

        image_file = st.file_uploader(
            "Upload an image for analysis",
            type=["png", "jpg", "jpeg", "webp"]
        )

        question = st.text_area(
            "What should VINCI examine?"
        )

        if st.button(
            "Analyze Image",
            use_container_width=True
        ):

            if not image_file:

                st.warning("Upload an image first.")

            else:

                try:

                    with st.spinner("Analyzing image..."):

                        answer = analyze_uploaded_image(
                            image_file.getvalue(),
                            image_file.type,
                            question or "Analyze this image."
                        )

                    st.session_state["image_result"] = {
                        "answer": answer
                    }

                except Exception as error:

                    st.error(str(error))

        result = st.session_state.get(
            "image_result"
        )

        if result and result.get("answer"):

            st.markdown(result["answer"])


# ============================================================
# 7. LIVE WITH VINCI
# ============================================================

def render_live_with_vinci():

    st.title("🎙️ Live with VINCI")

    st.write(
        "Upload an audio recording for transcription "
        "and AI-assisted analysis."
    )

    audio_file = st.file_uploader(
        "Upload audio",
        type=[
            "wav", "mp3", "mpeg",
            "mp4", "aac", "ogg",
            "webm", "flac"
        ]
    )

    if audio_file:

        st.audio(
            audio_file.getvalue(),
            format=audio_file.type
        )

    if st.button(
        "Transcribe Audio",
        use_container_width=True
    ):

        if not audio_file:

            st.warning("Upload an audio recording first.")

        else:

            try:

                with st.spinner("Transcribing audio..."):

                    transcription = transcribe_audio(
                        audio_file.getvalue(),
                        audio_file.type
                    )

                st.session_state["voice_result"] = (
                    transcription
                )

            except Exception as error:

                st.error(str(error))

    transcription = st.session_state.get(
        "voice_result"
    )

    if transcription:

        st.subheader("Transcription")

        st.text_area(
            "Recognized speech",
            value=transcription,
            height=200
        )

        if st.button("Save Transcription"):

            save_item(
                "Audio Transcription",
                transcription,
                "voice"
            )

            st.success("Transcription saved.")

    st.info(
        "This version supports audio upload and transcription. "
        "Continuous live microphone conversations and "
        "speech generation require a separate real-time "
        "voice service integration."
    )


# ============================================================
# 8. DESIGN STUDIO
# ============================================================

def render_design_studio():

    st.title("🖌️ Design Studio")

    st.write(
        "Develop creative concepts, product designs, "
        "technical descriptions and professional layouts."
    )

    design_type = st.selectbox(
        "Design category",
        [
            "Product Design",
            "Engineering Concept",
            "Business Branding",
            "Advertisement Concept",
            "Building and Architecture",
            "UI/UX Design",
            "Technical Illustration"
        ]
    )

    brief = st.text_area(
        "Describe your design project",
        height=160
    )

    if st.button(
        "Develop Design Concept",
        use_container_width=True
    ):

        if not brief.strip():

            st.warning("Describe your design first.")

        else:

            try:

                prompt = f"""
Develop a professional design concept.

CATEGORY:
{design_type}

PROJECT BRIEF:
{brief}

Provide:
1. Concept overview
2. Design objectives
3. Layout and structure
4. M
