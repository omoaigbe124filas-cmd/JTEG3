
# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 1 OF 6
# FOUNDATION, CONFIGURATION AND POSTGRESQL DATABASE
# ============================================================

import os
import io
import re
import json
import time
import uuid
import base64
import hashlib
import secrets
import logging
import mimetypes
from datetime import datetime, timezone, timedelta
from functools import wraps

import streamlit as st
import httpx
import bcrypt

from sqlalchemy import (
    create_engine,
    text,
    inspect,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool


# ------------------------------------------------------------
# APPLICATION CONFIGURATION
# ------------------------------------------------------------

APP_NAME = "Vinci AI"
APP_VERSION = "3.0"

APP_DESCRIPTION = (
    "The JTEG Intelligence Platform"
)

DEFAULT_CHAT_PRIMARY = "gemini-3.8-flash"
DEFAULT_CHAT_FALLBACK = "gemini-3.5-flash"

DEFAULT_RESEARCH_PRIMARY = "gemini-3.5-flash"
DEFAULT_RESEARCH_FALLBACK = "gemini-3.6-flash"

MAX_UPLOAD_MB = 15
MAX_DOCUMENT_CHARS = 50000

SESSION_DAYS = 30
VERIFICATION_MINUTES = 10

AI_POLICY = {
    "free_only": True,
    "allow_paid_models": False,
    "allow_automatic_purchases": False,
}

CHAT_MODELS = {
    "primary": DEFAULT_CHAT_PRIMARY,
    "fallback": DEFAULT_CHAT_FALLBACK,
}

RESEARCH_MODELS = {
    "primary": DEFAULT_RESEARCH_PRIMARY,
    "fallback": DEFAULT_RESEARCH_FALLBACK,
}

OPENROUTER_POLICY = {
    "enabled": True,
    "research_only": True,
    "image_only_for_approved_free_models": True,
    "allow_paid_models": False,
}


# ------------------------------------------------------------
# ENVIRONMENT AND SECRET MANAGEMENT
# ------------------------------------------------------------

def get_secret(name, default=""):
    """Read configuration from Streamlit secrets or environment."""

    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value)
    except Exception:
        pass

    return os.getenv(name, default)


DATABASE_URL = get_secret("DATABASE_URL")

GEMINI_API_KEY = get_secret("GEMINI_API_KEY")

OPENROUTER_API_KEY = get_secret("OPENROUTER_API_KEY")

OPENROUTER_BASE_URL = (
    "https://openrouter.ai/api/v1"
)

OPENROUTER_RESEARCH_MODEL = get_secret(
    "OPENROUTER_RESEARCH_MODEL",
    ""
)

OPENROUTER_IMAGE_MODEL = get_secret(
    "OPENROUTER_IMAGE_MODEL",
    ""
)

ADMIN_EMAILS = {
    email.strip().lower()
    for email in get_secret(
        "ADMIN_EMAILS", ""
    ).split(",")
    if email.strip()
}

SMTP_HOST = get_secret("SMTP_HOST")
SMTP_PORT = int(get_secret("SMTP_PORT", "587"))
SMTP_USERNAME = get_secret("SMTP_USERNAME")
SMTP_PASSWORD = get_secret("SMTP_PASSWORD")
SMTP_FROM_EMAIL = get_secret("SMTP_FROM_EMAIL")

COOKIE_SECRET = get_secret("COOKIE_SECRET")


# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

logger = logging.getLogger("vinci_ai")


# ------------------------------------------------------------
# STREAMLIT CONFIGURATION
# ------------------------------------------------------------

st.set_page_config(
    page_title="Vinci AI | JTEG",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ------------------------------------------------------------
# DATABASE CONNECTION
# ------------------------------------------------------------

@st.cache_resource
def get_database_engine():
    """
    Create the PostgreSQL connection pool.

    DATABASE_URL must point to a PostgreSQL database.
    SQLite is deliberately not used in this new version.
    """

    if not DATABASE_URL:
        return None

    if not DATABASE_URL.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):
        raise ValueError(
            "Vinci AI requires a PostgreSQL DATABASE_URL."
        )

    database_url = DATABASE_URL

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": 15,
        },
    )


def database_ready():
    try:
        engine = get_database_engine()

        if engine is None:
            return False

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return True

    except Exception as error:
        logger.error(
            "Database connection failed: %s",
            error,
        )
        return False


def execute_sql(query, parameters=None, fetch=False):
    """Execute parameterised SQL safely."""

    engine = get_database_engine()

    if engine is None:
        raise RuntimeError(
            "PostgreSQL DATABASE_URL is not configured."
        )

    with engine.begin() as connection:
        result = connection.execute(
            text(query),
            parameters or {},
        )

        if fetch:
            return [
                dict(row)
                for row in result.mappings().all()
            ]

        return result.rowcount


# ------------------------------------------------------------
# DATABASE INITIALISATION
# ------------------------------------------------------------

def initialize_database():
    """
    Create a completely new Vinci AI database schema.

    Existing SQLite data is not imported.
    No user chat contents are exposed to administrators.
    """

    statements = [

        """
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(36) PRIMARY KEY,
            full_name VARCHAR(200) NOT NULL,
            email VARCHAR(320) UNIQUE NOT NULL,
            phone VARCHAR(40) NOT NULL,
            job_description TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'user',
            is_verified BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login TIMESTAMPTZ,
            login_count INTEGER NOT NULL DEFAULT 0
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS verification_codes (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS sessions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(300) NOT NULL DEFAULT 'New conversation',
            workspace VARCHAR(40) NOT NULL DEFAULT 'chat',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            archived BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS messages (
            id VARCHAR(36) PRIMARY KEY,
            conversation_id VARCHAR(36) NOT NULL
                REFERENCES conversations(id) ON DELETE CASCADE,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            model VARCHAR(150),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS saved_items (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            item_type VARCHAR(40) NOT NULL,
            title VARCHAR(300) NOT NULL,
            content TEXT,
            source_id VARCHAR(36),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS library_files (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            filename VARCHAR(300) NOT NULL,
            storage_path TEXT NOT NULL,
            file_type VARCHAR(100),
            file_size BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS reminders (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(300) NOT NULL,
            description TEXT,
            scheduled_at TIMESTAMPTZ NOT NULL,
            completed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS workspace_sessions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            workspace VARCHAR(40) NOT NULL,
            state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, workspace)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS provider_usage (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            provider VARCHAR(80) NOT NULL,
            model VARCHAR(150) NOT NULL,
            workspace VARCHAR(40) NOT NULL,
            status VARCHAR(40) NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS admin_activity_logs (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36),
            email VARCHAR(320),
            activity VARCHAR(100) NOT NULL,
            ip_address VARCHAR(100),
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

    ]

    engine = get_database_engine()

    if engine is None:
        raise RuntimeError(
            "Configure DATABASE_URL before database setup."
        )

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    logger.info("Vinci AI PostgreSQL schema initialised.")


# ------------------------------------------------------------
# PASSWORD UTILITIES
# ------------------------------------------------------------

def hash_password(password):
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("utf-8")


def verify_password(password, password_hash):
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except Exception:
        return False


def hash_token(token):
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def new_id():
    return str(uuid.uuid4())


# ------------------------------------------------------------
# BASIC VALIDATION
# ------------------------------------------------------------

def valid_email(email):
    return bool(
        re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            email.strip().lower(),
        )
    )


def normalise_email(email):
    return email.strip().lower()


def utc_now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------
# APPLICATION STATE
# ------------------------------------------------------------

DEFAULT_STATE = {
    "authenticated": False,
    "user": None,
    "user_id": None,
    "role": "user",
    "active_workspace": "chat",
    "active_conversation": None,
    "workspace_sessions": {},
    "pending_transcription": "",
    "chat_input": "",
    "show_navigation": False,
    "show_login": True,
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# END OF BLOCK 1
# CONTINUE DIRECTLY WITH BLOCK 2
# ============================================================

# ============================================================
# VINCI AI — BLOCK 2 OF 6
# AUTHENTICATION, REGISTRATION AND ADMIN SECURITY
# ============================================================

import smtplib
from email.message import EmailMessage


# ------------------------------------------------------------
# EMAIL DELIVERY
# ------------------------------------------------------------

def send_email(recipient, subject, body):

    if not all([
        SMTP_HOST,
        SMTP_USERNAME,
        SMTP_PASSWORD,
        SMTP_FROM_EMAIL,
    ]):
        logger.warning(
            "Email configuration is incomplete."
        )
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = recipient
    message.set_content(body)

    try:
        with smtplib.SMTP(
            SMTP_HOST,
            SMTP_PORT,
            timeout=20,
        ) as server:

            server.starttls()

            server.login(
                SMTP_USERNAME,
                SMTP_PASSWORD,
            )

            server.send_message(message)

        return True

    except Exception as error:
        logger.error(
            "Email delivery failed: %s",
            error,
        )
        return False


def send_verification_email(email, code):

    subject = "Verify your Vinci AI account"

    body = f"""
Welcome to Vinci AI.

Your account verification code is:

{code}

This code expires in {VERIFICATION_MINUTES} minutes.

If you did not request this account, you can ignore this email.

JTEG Intelligence Platform
"""

    return send_email(
        email,
        subject,
        body,
    )


# ------------------------------------------------------------
# ACCOUNT LOOKUP
# ------------------------------------------------------------

def get_user_by_email(email):

    rows = execute_sql(
        """
        SELECT *
        FROM users
        WHERE email = :email
        LIMIT 1
        """,
        {
            "email": normalise_email(email),
        },
        fetch=True,
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
        {
            "user_id": user_id,
        },
        fetch=True,
    )

    return rows[0] if rows else None


# ------------------------------------------------------------
# ADMINISTRATOR ROLE MANAGEMENT
# ------------------------------------------------------------

def is_admin_email(email):

    return normalise_email(email) in ADMIN_EMAILS


def sync_user_role(user_id, email):

    role = (
        "admin"
        if is_admin_email(email)
        else "user"
    )

    execute_sql(
        """
        UPDATE users
        SET role = :role
        WHERE id = :user_id
        """,
        {
            "role": role,
            "user_id": user_id,
        },
    )

    return role


def current_user_is_admin():

    user = st.session_state.get("user")

    if not user:
        return False

    return (
        user.get("role") == "admin"
        and is_admin_email(user.get("email", ""))
    )


# ------------------------------------------------------------
# REGISTRATION
# ------------------------------------------------------------

def register_user(
    full_name,
    email,
    phone,
    job_description,
    password,
):
    full_name = full_name.strip()
    email = normalise_email(email)
    phone = phone.strip()
    job_description = job_description.strip()

    if not all([
        full_name,
        email,
        phone,
        job_description,
        password,
    ]):
        return False, "Please complete every field."

    if not valid_email(email):
        return False, "Enter a valid email address."

    if len(full_name) < 2:
        return False, "Enter your full name."

    if len(password) < 10:
        return False, (
            "Your password must contain at least "
            "10 characters."
        )

    if get_user_by_email(email):
        return False, (
            "An account already exists with this email."
        )

    user_id = new_id()

    role = (
        "admin"
        if is_admin_email(email)
        else "user"
    )

    password_hash = hash_password(password)

    execute_sql(
        """
        INSERT INTO users (
            id,
            full_name,
            email,
            phone,
            job_description,
            password_hash,
            role,
            is_verified,
            is_active
        )
        VALUES (
            :id,
            :full_name,
            :email,
            :phone,
            :job_description,
            :password_hash,
            :role,
            FALSE,
            TRUE
        )
        """,
        {
            "id": user_id,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "job_description": job_description,
            "password_hash": password_hash,
            "role": role,
        },
    )

    code = f"{secrets.randbelow(1000000):06d}"

    execute_sql(
        """
        INSERT INTO verification_codes (
            id,
            user_id,
            code_hash,
            expires_at,
            attempts
        )
        VALUES (
            :id,
            :user_id,
            :code_hash,
            :expires_at,
            0
        )
        """,
        {
            "id": new_id(),
            "user_id": user_id,
            "code_hash": hash_token(code),
            "expires_at": (
                utc_now()
                + timedelta(minutes=VERIFICATION_MINUTES)
            ),
        },
    )

    if not send_verification_email(email, code):

        logger.warning(
            "Verification email could not be delivered."
        )

        return True, (
            "Your account was created, but verification "
            "email delivery failed. Contact the administrator "
            "or check the email configuration."
        )

    return True, (
        "Your account has been created. "
        "Check your email for the verification code."
    )


# ------------------------------------------------------------
# EMAIL VERIFICATION
# ------------------------------------------------------------

def verify_registration_code(email, code):

    email = normalise_email(email)

    user = get_user_by_email(email)

    if not user:
        return False, "Account not found."

    if user["is_verified"]:
        return True, "Your account is already verified."

    records = execute_sql(
        """
        SELECT *
        FROM verification_codes
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {
            "user_id": user["id"],
        },
        fetch=True,
    )

    if not records:
        return False, "No verification code was found."

    record = records[0]

    if record["expires_at"] < utc_now():
        return False, "Your verification code has expired."

    if record["attempts"] >= 5:
        return False, (
            "Too many attempts. Request a new code."
        )

    if not secrets.compare_digest(
        record["code_hash"],
        hash_token(code.strip()),
    ):

        execute_sql(
            """
            UPDATE verification_codes
            SET attempts = attempts + 1
            WHERE id = :id
            """,
            {
                "id": record["id"],
            },
        )

        return False, "Incorrect verification code."

    execute_sql(
        """
        UPDATE users
        SET is_verified = TRUE
        WHERE id = :user_id
        """,
        {
            "user_id": user["id"],
        },
    )

    execute_sql(
        """
        DELETE FROM verification_codes
        WHERE user_id = :user_id
        """,
        {
            "user_id": user["id"],
        },
    )

    return True, "Your email has been verified."


def resend_verification_code(email):

    email = normalise_email(email)

    user = get_user_by_email(email)

    if not user:
        return False, "Account not found."

    if user["is_verified"]:
        return False, "Your account is already verified."

    code = f"{secrets.randbelow(1000000):06d}"

    execute_sql(
        """
        DELETE FROM verification_codes
        WHERE user_id = :user_id
        """,
        {
            "user_id": user["id"],
        },
    )

    execute_sql(
        """
        INSERT INTO verification_codes (
            id,
            user_id,
            code_hash,
            expires_at,
            attempts
        )
        VALUES (
            :id,
            :user_id,
            :code_hash,
            :expires_at,
            0
        )
        """,
        {
            "id": new_id(),
            "user_id": user["id"],
            "code_hash": hash_token(code),
            "expires_at": (
                utc_now()
                + timedelta(minutes=VERIFICATION_MINUTES)
            ),
        },
    )

    if send_verification_email(email, code):
        return True, "A new verification code has been sent."

    return False, "Email delivery failed."


# ------------------------------------------------------------
# LOGIN ACTIVITY LOGGING
# ------------------------------------------------------------

def record_login_activity(user):

    execute_sql(
        """
        UPDATE users
        SET
            last_login = NOW(),
            login_count = login_count + 1
        WHERE id = :user_id
        """,
        {
            "user_id": user["id"],
        },
    )

    execute_sql(
        """
        INSERT INTO admin_activity_logs (
            id,
            user_id,
            email,
            activity
        )
        VALUES (
            :id,
            :user_id,
            :email,
            'successful_login'
        )
        """,
        {
            "id": new_id(),
            "user_id": user["id"],
            "email": user["email"],
        },
    )


# ------------------------------------------------------------
# SESSION CREATION
# ------------------------------------------------------------

def create_user_session(user_id):

    raw_token = secrets.token_urlsafe(48)

    execute_sql(
        """
        INSERT INTO sessions (
            id,
            user_id,
            token_hash,
            expires_at,
            revoked
        )
        VALUES (
            :id,
            :user_id,
            :token_hash,
            :expires_at,
            FALSE
        )
        """,
        {
            "id": new_id(),
            "user_id": user_id,
            "token_hash": hash_token(raw_token),
            "expires_at": (
                utc_now()
                + timedelta(days=SESSION_DAYS)
            ),
        },
    )

    st.session_state["auth_token"] = raw_token

    return raw_token


def validate_user_session(raw_token):

    if not raw_token:
        return None

    rows = execute_sql(
        """
        SELECT
            users.*,
            sessions.id AS session_id
        FROM sessions
        JOIN users
            ON users.id = sessions.user_id
        WHERE sessions.token_hash = :token_hash
          AND sessions.expires_at > NOW()
          AND sessions.revoked = FALSE
          AND users.is_active = TRUE
          AND users.is_verified = TRUE
        LIMIT 1
        """,
        {
            "token_hash": hash_token(raw_token),
        },
        fetch=True,
    )

    return rows[0] if rows else None


def revoke_user_session():

    raw_token = st.session_state.get("auth_token")

    if raw_token:

        execute_sql(
            """
            UPDATE sessions
            SET revoked = TRUE
            WHERE token_hash = :token_hash
            """,
            {
                "token_hash": hash_token(raw_token),
            },
        )

    st.session_state["auth_token"] = None


# ------------------------------------------------------------
# LOGIN
# ------------------------------------------------------------

def authenticate_user(email, password):

    email = normalise_email(email)

    user = get_user_by_email(email)

    if not user:
        return False, "Invalid email or password."

    if not user["is_active"]:
        return False, "This account is inactive."

    if not verify_password(
        password,
        user["password_hash"],
    ):
        return False, "Invalid email or password."

    if not user["is_verified"]:
        return False, (
            "Please verify your email before signing in."
        )

    role = sync_user_role(
        user["id"],
        user["email"],
    )

    user["role"] = role

    record_login_activity(user)

    create_user_session(user["id"])

    st.session_state["authenticated"] = True
    st.session_state["user_id"] = user["id"]
    st.session_state["user"] = {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "phone": user["phone"],
        "job_description": user["job_description"],
        "role": role,
    }

    st.session_state["show_login"] = False
    st.session_state["active_workspace"] = "chat"
    st.session_state["active_conversation"] = None

    return True, "Welcome to Vinci AI."


# ------------------------------------------------------------
# SESSION RESTORATION
# ------------------------------------------------------------

def restore_authenticated_session():

    if st.session_state.get("authenticated"):
        return True

    token = st.session_state.get("auth_token")

    if not token:
        return False

    user = validate_user_session(token)

    if not user:
        st.session_state["auth_token"] = None
        return False

    role = sync_user_role(
        user["id"],
        user["email"],
    )

    st.session_state["authenticated"] = True
    st.session_state["user_id"] = user["id"]

    st.session_state["user"] = {
        "id": user["id"],
        "full_name": user["full_name"],
        "email": user["email"],
        "phone": user["phone"],
        "job_description": user["job_description"],
        "role": role,
    }

    st.session_state["show_login"] = False

    return True


# ------------------------------------------------------------
# LOGOUT
# ------------------------------------------------------------

def logout_user():

    try:
        revoke_user_session()
    except Exception as error:
        logger.error(
            "Session revocation failed: %s",
            error,
        )

    for key in [
        "authenticated",
        "user",
        "user_id",
        "auth_token",
        "active_workspace",
        "active_conversation",
        "workspace_sessions",
        "pending_transcription",
    ]:
        st.session_state[key] = None

    st.session_state["authenticated"] = False
    st.session_state["user"] = None
    st.session_state["user_id"] = None
    st.session_state["active_workspace"] = "chat"
    st.session_state["show_login"] = True


# ------------------------------------------------------------
# ADMIN PRIVACY AND ACCESS CONTROL
# ------------------------------------------------------------

def require_admin():

    if not st.session_state.get("authenticated"):
        st.error("Authentication required.")
        st.stop()

    if not current_user_is_admin():
        st.error("Administrator access denied.")
        st.stop()


def get_admin_user_records():

    require_admin()

    return execute_sql(
        """
        SELECT
            id,
            full_name,
            email,
            phone,
            job_description,
            role,
            is_verified,
            is_active,
            created_at,
            last_login,
            login_count
        FROM users
        ORDER BY created_at DESC
        """,
        fetch=True,
    )


def get_admin_login_activity(limit=200):

    require_admin()

    limit = max(1, min(int(limit), 500))

    return execute_sql(
        """
        SELECT
            id,
            user_id,
            email,
            activity,
            created_at
        FROM admin_activity_logs
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {
            "limit": limit,
        },
        fetch=True,
    )


def get_admin_database_statistics():

    require_admin()

    users = execute_sql(
        """
        SELECT COUNT(*) AS total
        FROM users
        """,
        fetch=True,
    )[0]["total"]

    verified = execute_sql(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE is_verified = TRUE
        """,
        fetch=True,
    )[0]["total"]

    active_sessions = execute_sql(
        """
        SELECT COUNT(*) AS total
        FROM sessions
        WHERE revoked = FALSE
          AND expires_at > NOW()
        """,
        fetch=True,
    )[0]["total"]

    logins = execute_sql(
        """
        SELECT COUNT(*) AS total
        FROM admin_activity_logs
        WHERE activity = 'successful_login'
        """,
        fetch=True,
    )[0]["total"]

    return {
        "users": users,
        "verified_users": verified,
        "active_sessions": active_sessions,
        "successful_logins": logins,
    }


# ============================================================
# END OF BLOCK 2
# CONTINUE DIRECTLY WITH BLOCK 3
# ============================================================

# ============================================================
# VINCI AI — BLOCK 3 OF 6
# GEMINI + OPENROUTER PROVIDER ENGINE
# ============================================================

import asyncio


# ------------------------------------------------------------
# PROVIDER CONFIGURATION
# ------------------------------------------------------------

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
)

OPENROUTER_MODELS_URL = (
    "https://openrouter.ai/api/v1/models"
)

OPENROUTER_CHAT_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

CHAT_PRIMARY_MODEL = get_secret(
    "CHAT_PRIMARY_MODEL",
    DEFAULT_CHAT_PRIMARY,
)

CHAT_FALLBACK_MODEL = get_secret(
    "CHAT_FALLBACK_MODEL",
    DEFAULT_CHAT_FALLBACK,
)

RESEARCH_PRIMARY_MODEL = get_secret(
    "RESEARCH_PRIMARY_MODEL",
    DEFAULT_RESEARCH_PRIMARY,
)

RESEARCH_FALLBACK_MODEL = get_secret(
    "RESEARCH_FALLBACK_MODEL",
    DEFAULT_RESEARCH_FALLBACK,
)

OPENROUTER_RESEARCH_MODEL = get_secret(
    "OPENROUTER_RESEARCH_MODEL",
    "",
)

AI_REQUEST_TIMEOUT = 90

MAX_AI_OUTPUT_TOKENS = 4096

AI_TEMPERATURE = 0.6


# ------------------------------------------------------------
# PROVIDER STATUS
# ------------------------------------------------------------

def provider_status():

    return {
        "gemini": {
            "configured": bool(GEMINI_API_KEY),
            "chat_primary": CHAT_PRIMARY_MODEL,
            "chat_fallback": CHAT_FALLBACK_MODEL,
            "research_primary": RESEARCH_PRIMARY_MODEL,
            "research_fallback": RESEARCH_FALLBACK_MODEL,
        },

        "openrouter": {
            "configured": bool(OPENROUTER_API_KEY),
            "research_enabled": bool(
                OPENROUTER_API_KEY
                and OPENROUTER_POLICY["enabled"]
            ),
            "research_model": (
                OPENROUTER_RESEARCH_MODEL
                or "Not configured"
            ),
            "paid_models_allowed": False,
        },
    }


# ------------------------------------------------------------
# MODEL REQUEST HELPERS
# ------------------------------------------------------------

def normalise_history(history):

    normalised = []

    for item in history:

        if not isinstance(item, dict):
            continue

        role = item.get("role", "user")

        content = str(
            item.get("content", "")
        ).strip()

        if not content:
            continue

        if role not in ["user", "assistant", "model"]:
            continue

        if role == "assistant":
            role = "model"

        normalised.append({
            "role": role,
            "content": content,
        })

    return normalised


def build_gemini_contents(history):

    contents = []

    for item in normalise_history(history):

        role = item["role"]

        if role == "model":
            role = "model"

        contents.append({
            "role": role,
            "parts": [
                {
                    "text": item["content"]
                }
            ],
        })

    return contents


# ------------------------------------------------------------
# GEMINI API REQUEST
# ------------------------------------------------------------

def ask_gemini(
    prompt,
    history=None,
    system_instruction=None,
    model=None,
    temperature=None,
    max_output_tokens=None,
):
    """
    Direct Gemini REST API integration.

    This avoids depending on an unverified SDK method signature.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Gemini API key is not configured."
        )

    model = model or CHAT_PRIMARY_MODEL

    history = history or []

    contents = build_gemini_contents(history)

    contents.append({
        "role": "user",
        "parts": [
            {
                "text": str(prompt)
            }
        ],
    })

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": (
                AI_TEMPERATURE
                if temperature is None
                else temperature
            ),
            "maxOutputTokens": (
                MAX_AI_OUTPUT_TOKENS
                if max_output_tokens is None
                else max_output_tokens
            ),
        },
    }

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [
                {
                    "text": str(system_instruction)
                }
            ]
        }

    endpoint = (
        f"{GEMINI_API_URL}/{model}:generateContent"
    )

    response = httpx.post(
        endpoint,
        params={
            "key": GEMINI_API_KEY,
        },
        json=payload,
        timeout=AI_REQUEST_TIMEOUT,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Gemini API error "
            f"{response.status_code}: "
            f"{response.text[:1000]}"
        )

    data = response.json()

    candidates = data.get("candidates", [])

    if not candidates:
        raise RuntimeError(
            "Gemini returned no response candidates."
        )

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
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    usage = data.get("usageMetadata", {})

    return {
        "text": answer,
        "provider": "Gemini",
        "model": model,
        "input_tokens": usage.get(
            "promptTokenCount", 0
        ),
        "output_tokens": usage.get(
            "candidatesTokenCount", 0
        ),
    }


# ------------------------------------------------------------
# OPENROUTER FREE-MODEL VALIDATION
# ------------------------------------------------------------

@st.cache_data(ttl=900)
def get_openrouter_free_models():

    if not OPENROUTER_API_KEY:
        return []

    try:

        response = httpx.get(
            OPENROUTER_MODELS_URL,
            headers={
                "Authorization": (
                    f"Bearer {OPENROUTER_API_KEY}"
                ),
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        free_models = []

        for item in data.get("data", []):

            pricing = item.get("pricing", {})

            prompt_price = str(
                pricing.get("prompt", "")
            )

            completion_price = str(
                pricing.get("completion", "")
            )

            try:
                is_free = (
                    float(prompt_price) == 0
                    and float(completion_price) == 0
                )
            except (TypeError, ValueError):
                is_free = False

            if not is_free:
                continue

            model_id = item.get("id", "")

            if not model_id:
                continue

            free_models.append({
                "id": model_id,
                "name": item.get(
                    "name",
                    model_id,
                ),
            })

        return free_models

    except Exception as error:

        logger.warning(
            "OpenRouter model discovery failed: %s",
            error,
        )

        return []


def validate_openrouter_free_model(model_id):

    if not OPENROUTER_API_KEY:
        return False

    if not model_id:
        return False

    models = get_openrouter_free_models()

    return any(
        item["id"] == model_id
        for item in models
    )


# ------------------------------------------------------------
# OPENROUTER RESEARCH REQUEST
# ------------------------------------------------------------

def ask_openrouter_research(
    prompt,
    history=None,
    system_instruction=None,
    model=None,
):
    """
    OpenRouter is restricted to Deep Research.

    A model is accepted only if the live model catalogue
    reports zero input and output token pricing.
    """

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OpenRouter API key is not configured."
        )

    if not OPENROUTER_POLICY["enabled"]:
        raise RuntimeError(
            "OpenRouter research access is disabled."
        )

    selected_model = (
        model
        or OPENROUTER_RESEARCH_MODEL
    )

    if not selected_model:
        raise RuntimeError(
            "No OpenRouter research model configured."
        )

    if not validate_openrouter_free_model(
        selected_model
    ):
        raise RuntimeError(
            "The selected OpenRouter model is not "
            "verified as free. Paid-model requests blocked."
        )

    messages = []

    if system_instruction:
        messages.append({
            "role": "system",
            "content": str(system_instruction),
        })

    for item in normalise_history(history or []):

        messages.append({
            "role": (
                "assistant"
                if item["role"] == "model"
                else item["role"]
            ),
            "content": item["content"],
        })

    messages.append({
        "role": "user",
        "content": str(prompt),
    })

    payload = {
        "model": selected_model,
        "messages": messages,
        "temperature": AI_TEMPERATURE,
        "max_tokens": MAX_AI_OUTPUT_TOKENS,
    }

    response = httpx.post(
        OPENROUTER_CHAT_URL,
        headers={
            "Authorization": (
                f"Bearer {OPENROUTER_API_KEY}"
            ),
            "Content-Type": "application/json",
            "HTTP-Referer": (
                "https://vinci-ai.jteg"
            ),
            "X-Title": "Vinci AI",
        },
        json=payload,
        timeout=AI_REQUEST_TIMEOUT,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"OpenRouter API error "
            f"{response.status_code}: "
            f"{response.text[:1000]}"
        )

    data = response.json()

    choices = data.get("choices", [])

    if not choices:
        raise RuntimeError(
            "OpenRouter returned no response."
        )

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

    answer = str(answer).strip()

    if not answer:
        raise RuntimeError(
            "OpenRouter returned an empty response."
        )

    usage = data.get("usage", {})

    return {
        "text": answer,
        "provider": "OpenRouter",
        "model": selected_model,
        "input_tokens": usage.get(
            "prompt_tokens", 0
        ),
        "output_tokens": usage.get(
            "completion_tokens", 0
        ),
    }


# ------------------------------------------------------------
# PROVIDER USAGE RECORDING
# ------------------------------------------------------------

def record_provider_usage(
    provider,
    model,
    workspace,
    status,
    input_tokens=0,
    output_tokens=0,
):

    user_id = st.session_state.get("user_id")

    try:

        execute_sql(
            """
            INSERT INTO provider_usage (
                id,
                user_id,
                provider,
                model,
                workspace,
                status,
                input_tokens,
                output_tokens
            )
            VALUES (
                :id,
                :user_id,
                :provider,
                :model,
                :workspace,
                :status,
                :input_tokens,
                :output_tokens
            )
            """,
            {
                "id": new_id(),
                "user_id": user_id,
                "provider": provider,
                "model": model,
                "workspace": workspace,
                "status": status,
                "input_tokens": int(
                    input_tokens or 0
                ),
                "output_tokens": int(
                    output_tokens or 0
                ),
            },
        )

    except Exception as error:

        logger.warning(
            "Provider usage recording failed: %s",
            error,
        )


# ------------------------------------------------------------
# GENERAL CHAT ROUTER
# ------------------------------------------------------------

def generate_chat_answer(
    prompt,
    history=None,
):

    attempts = [
        (
            "Gemini",
            CHAT_PRIMARY_MODEL,
        ),
        (
            "Gemini",
            CHAT_FALLBACK_MODEL,
        ),
    ]

    failures = []

    for provider, model in attempts:

        try:

            result = ask_gemini(
                prompt=prompt,
                history=history,
                model=model,
                system_instruction=(
                    "You are Vinci AI, the intelligent "
                    "assistant of the JTEG Intelligence "
                    "Platform. Give accurate, useful, "
                    "clear and well-structured answers. "
                    "Do not invent sources or facts."
                ),
            )

            record_provider_usage(
                provider="Gemini",
                model=model,
                workspace="chat",
                status="success",
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
            )

            return result

        except Exception as error:

            failures.append(
                f"{model}: {str(error)[:250]}"
            )

            record_provider_usage(
                provider="Gemini",
                model=model,
                workspace="chat",
                status="failed",
            )

            logger.warning(
                "Chat model %s failed: %s",
                model,
                error,
            )

    raise RuntimeError(
        "All general chat models failed. "
        + " | ".join(failures)
    )


# ------------------------------------------------------------
# DEEP RESEARCH MODEL ROUTER
# ------------------------------------------------------------

def generate_research_answer(
    prompt,
    history=None,
    use_openrouter=False,
):

    """
    Gemini remains the configured research primary
    and fallback.

    OpenRouter is an optional research-only route.
    It is never used for ordinary chat.
    """

    if use_openrouter:

        try:

            result = ask_openrouter_research(
                prompt=prompt,
                history=history,
                system_instruction=(
                    "You are Vinci AI Deep Research. "
                    "Produce rigorous, structured analysis. "
                    "Distinguish verified facts from "
                    "uncertainty and avoid fabricated citations."
                ),
            )

            record_provider_usage(
                provider="OpenRouter",
                model=result["model"],
                workspace="deep_research",
                status="success",
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
            )

            return result

        except Exception as error:

            logger.warning(
                "OpenRouter research route unavailable: %s",
                error,
            )

            record_provider_usage(
                provider="OpenRouter",
                model=(
                    OPENROUTER_RESEARCH_MODEL
                    or "unconfigured"
                ),
                workspace="deep_research",
                status="failed",
            )

    attempts = [
        RESEARCH_PRIMARY_MODEL,
        RESEARCH_FALLBACK_MODEL,
    ]

    failures = []

    for model in attempts:

        try:

            result = ask_gemini(
                prompt=prompt,
                history=history,
                model=model,
                temperature=0.3,
                max_output_tokens=MAX_AI_OUTPUT_TOKENS,
                system_instruction=(
                    "You are Vinci AI Professional Deep "
                    "Research. Analyse the question carefully. "
                    "Organise the answer into an executive "
                    "summary, detailed findings, evidence, "
                    "limitations and conclusion. Never "
                    "invent references, URLs or quotations."
                ),
            )

            record_provider_usage(
                provider="Gemini",
                model=model,
                workspace="deep_research",
                status="success",
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
            )

            return result

        except Exception as error:

            failures.append(
                f"{model}: {str(error)[:250]}"
            )

            record_provider_usage(
                provider="Gemini",
                model=model,
                workspace="deep_research",
                status="failed",
            )

            logger.warning(
                "Research model %s failed: %s",
                model,
                error,
            )

    raise RuntimeError(
        "All research models failed. "
        + " | ".join(failures)
    )


# ------------------------------------------------------------
# MODEL CONNECTION TESTS
# ------------------------------------------------------------

def test_gemini_connection(model):

    try:

        result = ask_gemini(
            prompt=(
                "Reply with exactly: "
                "Vinci AI connection successful."
            ),
            model=model,
            max_output_tokens=50,
        )

        return {
            "success": True,
            "model": model,
            "message": result["text"],
        }

    except Exception as error:

        return {
            "success": False,
            "model": model,
            "message": str(error),
        }


def test_openrouter_connection():

    if not OPENROUTER_RESEARCH_MODEL:
        return {
            "success": False,
            "message": (
                "Configure OPENROUTER_RESEARCH_MODEL "
                "with a verified free model ID."
            ),
        }

    try:

        result = ask_openrouter_research(
            prompt=(
                "Reply with exactly: "
                "Vinci AI OpenRouter connection successful."
            ),
            model=OPENROUTER_RESEARCH_MODEL,
        )

        return {
            "success": True,
            "model": result["model"],
            "message": result["text"],
        }

    except Exception as error:

        return {
            "success": False,
            "model": OPENROUTER_RESEARCH_MODEL,
            "message": str(error),
        }


# ============================================================
# END OF BLOCK 3
# CONTINUE DIRECTLY WITH BLOCK 4
# ============================================================

# ============================================================
# VINCI AI — BLOCK 4 OF 6
# CONVERSATIONS, SAVED, LIBRARY AND SCHEDULE
# ============================================================

from pathlib import Path
from pypdf import PdfReader
from docx import Document


# ------------------------------------------------------------
# FILE STORAGE CONFIGURATION
# ------------------------------------------------------------

STORAGE_ROOT = Path(
    get_secret(
        "VINCI_STORAGE_PATH",
        "vinci_storage",
    )
)

UPLOAD_DIRECTORY = STORAGE_ROOT / "uploads"
IMAGE_DIRECTORY = STORAGE_ROOT / "images"
AUDIO_DIRECTORY = STORAGE_ROOT / "audio"

for directory in [
    STORAGE_ROOT,
    UPLOAD_DIRECTORY,
    IMAGE_DIRECTORY,
    AUDIO_DIRECTORY,
]:
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )


# ------------------------------------------------------------
# ADDITIONAL DATABASE TABLES
# ------------------------------------------------------------

def initialize_extended_database():

    statements = [

        """
        CREATE TABLE IF NOT EXISTS generated_images (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            prompt TEXT NOT NULL,
            image_path TEXT NOT NULL,
            model VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_conversations_user
        ON conversations(user_id, updated_at DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
        ON messages(conversation_id, created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_saved_user
        ON saved_items(user_id, created_at DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_reminders_user
        ON reminders(user_id, scheduled_at)
        """,

    ]

    engine = get_database_engine()

    if engine is None:
        raise RuntimeError(
            "PostgreSQL is not configured."
        )

    with engine.begin() as connection:

        for statement in statements:
            connection.execute(text(statement))


# ------------------------------------------------------------
# CONVERSATION MANAGEMENT
# ------------------------------------------------------------

def create_conversation(
    title="New conversation",
    workspace="chat",
):

    user_id = st.session_state.get("user_id")

    if not user_id:
        raise RuntimeError(
            "User authentication is required."
        )

    conversation_id = new_id()

    execute_sql(
        """
        INSERT INTO conversations (
            id,
            user_id,
            title,
            workspace
        )
        VALUES (
            :id,
            :user_id,
            :title,
            :workspace
        )
        """,
        {
            "id": conversation_id,
            "user_id": user_id,
            "title": title[:300],
            "workspace": workspace,
        },
    )

    return conversation_id


def owns_conversation(conversation_id):

    if not conversation_id:
        return False

    rows = execute_sql(
        """
        SELECT id
        FROM conversations
        WHERE id = :conversation_id
          AND user_id = :user_id
        LIMIT 1
        """,
        {
            "conversation_id": conversation_id,
            "user_id": st.session_state.get("user_id"),
        },
        fetch=True,
    )

    return bool(rows)


def save_message(
    conversation_id,
    role,
    content,
    model=None,
):

    if not owns_conversation(conversation_id):
        raise PermissionError(
            "You do not own this conversation."
        )

    if role not in ["user", "assistant"]:
        raise ValueError("Invalid message role.")

    message_id = new_id()

    execute_sql(
        """
        INSERT INTO messages (
            id,
            conversation_id,
            user_id,
            role,
            content,
            model
        )
        VALUES (
            :id,
            :conversation_id,
            :user_id,
            :role,
            :content,
            :model
        )
        """,
        {
            "id": message_id,
            "conversation_id": conversation_id,
            "user_id": st.session_state["user_id"],
            "role": role,
            "content": str(content),
            "model": model,
        },
    )

    execute_sql(
        """
        UPDATE conversations
        SET updated_at = NOW()
        WHERE id = :conversation_id
        """,
        {
            "conversation_id": conversation_id,
        },
    )

    return message_id


def read_messages(conversation_id):

    if not owns_conversation(conversation_id):
        return []

    return execute_sql(
        """
        SELECT
            id,
            role,
            content,
            model,
            created_at
        FROM messages
        WHERE conversation_id = :conversation_id
          AND user_id = :user_id
        ORDER BY created_at ASC
        """,
        {
            "conversation_id": conversation_id,
            "user_id": st.session_state["user_id"],
        },
        fetch=True,
    )


def list_conversations(workspace=None):

    query = """
        SELECT
            id,
            title,
            workspace,
            created_at,
            updated_at
        FROM conversations
        WHERE user_id = :user_id
          AND archived = FALSE
    """

    parameters = {
        "user_id": st.session_state["user_id"],
    }

    if workspace:
        query += " AND workspace = :workspace"
        parameters["workspace"] = workspace

    query += " ORDER BY updated_at DESC"

    return execute_sql(
        query,
        parameters,
        fetch=True,
    )


def rename_conversation(
    conversation_id,
    new_title,
):

    if not owns_conversation(conversation_id):
        return False

    execute_sql(
        """
        UPDATE conversations
        SET title = :title,
            updated_at = NOW()
        WHERE id = :conversation_id
          AND user_id = :user_id
        """,
        {
            "title": new_title.strip()[:300],
            "conversation_id": conversation_id,
            "user_id": st.session_state["user_id"],
        },
    )

    return True


def archive_conversation(conversation_id):

    if not owns_conversation(conversation_id):
        return False

    execute_sql(
        """
        UPDATE conversations
        SET archived = TRUE
        WHERE id = :conversation_id
          AND user_id = :user_id
        """,
        {
            "conversation_id": conversation_id,
            "user_id": st.session_state["user_id"],
        },
    )

    if (
        st.session_state.get("active_conversation")
        == conversation_id
    ):
        st.session_state["active_conversation"] = None

    return True


def start_new_chat(workspace="chat"):

    conversation_id = create_conversation(
        workspace=workspace,
    )

    st.session_state["active_conversation"] = (
        conversation_id
    )

    st.session_state["active_workspace"] = workspace

    return conversation_id


# ------------------------------------------------------------
# MESSAGE SAVING AND PERSONAL CONTENT
# ------------------------------------------------------------

def save_item(
    item_type,
    title,
    content,
    source_id=None,
):

    item_id = new_id()

    execute_sql(
        """
        INSERT INTO saved_items (
            id,
            user_id,
            item_type,
            title,
            content,
            source_id
        )
        VALUES (
            :id,
            :user_id,
            :item_type,
            :title,
            :content,
            :source_id
        )
        """,
        {
            "id": item_id,
            "user_id": st.session_state["user_id"],
            "item_type": item_type,
            "title": title[:300],
            "content": content,
            "source_id": source_id,
        },
    )

    return item_id


def get_saved_items(item_type=None):

    query = """
        SELECT *
        FROM saved_items
        WHERE user_id = :user_id
    """

    parameters = {
        "user_id": st.session_state["user_id"],
    }

    if item_type:
        query += " AND item_type = :item_type"
        parameters["item_type"] = item_type

    query += " ORDER BY created_at DESC"

    return execute_sql(
        query,
        parameters,
        fetch=True,
    )


def delete_saved_item(item_id):

    execute_sql(
        """
        DELETE FROM saved_items
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": item_id,
            "user_id": st.session_state["user_id"],
        },
    )


# ------------------------------------------------------------
# DOCUMENT EXTRACTION
# ------------------------------------------------------------

def extract_document_text(
    filename,
    file_bytes,
):

    extension = Path(filename).suffix.lower()

    try:

        if extension == ".pdf":

            reader = PdfReader(
                io.BytesIO(file_bytes)
            )

            content = "\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )

        elif extension == ".docx":

            document = Document(
                io.BytesIO(file_bytes)
            )

            content = "\n".join(
                paragraph.text
                for paragraph in document.paragraphs
            )

        elif extension in [
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".py",
            ".html",
        ]:

            content = file_bytes.decode(
                "utf-8",
                errors="replace",
            )

        else:

            return None, (
                "This document format is not supported."
            )

        return (
            content[:MAX_DOCUMENT_CHARS],
            None,
        )

    except Exception as error:

        logger.warning(
            "Document extraction failed: %s",
            error,
        )

        return None, (
            "Unable to extract text from this document."
        )


# ------------------------------------------------------------
# LIBRARY FILE MANAGEMENT
# ------------------------------------------------------------

def store_library_file(
    filename,
    file_bytes,
):

    user_id = st.session_state["user_id"]

    if len(file_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(
            "The file exceeds the upload limit."
        )

    extension = Path(filename).suffix.lower()

    if not re.fullmatch(
        r"\.[a-z0-9]{1,10}",
        extension,
    ):
        extension = ".bin"

    file_id = new_id()

    safe_filename = (
        file_id + extension
    )

    destination = (
        UPLOAD_DIRECTORY / safe_filename
    )

    destination.write_bytes(file_bytes)

    execute_sql(
        """
        INSERT INTO library_files (
            id,
            user_id,
            filename,
            storage_path,
            file_type,
            file_size
        )
        VALUES (
            :id,
            :user_id,
            :filename,
            :storage_path,
            :file_type,
            :file_size
        )
        """,
        {
            "id": file_id,
            "user_id": user_id,
            "filename": Path(filename).name[:300],
            "storage_path": str(destination),
            "file_type": mimetypes.guess_type(filename)[0],
            "file_size": len(file_bytes),
        },
    )

    return file_id


def get_library_files():

    return execute_sql(
        """
        SELECT
            id,
            filename,
            file_type,
            file_size,
            created_at
        FROM library_files
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        """,
        {
            "user_id": st.session_state["user_id"],
        },
        fetch=True,
    )


def read_library_file(file_id):

    rows = execute_sql(
        """
        SELECT *
        FROM library_files
        WHERE id = :id
          AND user_id = :user_id
        LIMIT 1
        """,
        {
            "id": file_id,
            "user_id": st.session_state["user_id"],
        },
        fetch=True,
    )

    if not rows:
        raise PermissionError(
            "This file does not belong to your account."
        )

    path = Path(rows[0]["storage_path"])

    if not path.exists():
        raise FileNotFoundError(
            "The stored file is unavailable."
        )

    return rows[0], path.read_bytes()


def delete_library_file(file_id):

    rows = execute_sql(
        """
        SELECT storage_path
        FROM library_files
        WHERE id = :id
          AND user_id = :user_id
        LIMIT 1
        """,
        {
            "id": file_id,
            "user_id": st.session_state["user_id"],
        },
        fetch=True,
    )

    if not rows:
        return False

    path = Path(rows[0]["storage_path"])

    if path.exists():
        path.unlink()

    execute_sql(
        """
        DELETE FROM library_files
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": file_id,
            "user_id": st.session_state["user_id"],
        },
    )

    return True


# ------------------------------------------------------------
# DOCUMENT UPLOAD PROCESSING
# ------------------------------------------------------------

def process_uploaded_document(uploaded_file):

    if uploaded_file is None:
        return None

    file_bytes = uploaded_file.getvalue()

    if len(file_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(
            f"Maximum upload size is {MAX_UPLOAD_MB} MB."
        )

    extracted_text, error = extract_document_text(
        uploaded_file.name,
        file_bytes,
    )

    file_id = store_library_file(
        uploaded_file.name,
        file_bytes,
    )

    return {
        "id": file_id,
        "filename": uploaded_file.name,
        "text": extracted_text or "",
        "error": error,
    }


# ------------------------------------------------------------
# SCHEDULE AND REMINDERS
# ------------------------------------------------------------

def create_reminder(
    title,
    description,
    scheduled_at,
):

    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(
            tzinfo=timezone.utc
        )

    if scheduled_at <= utc_now():
        raise ValueError(
            "Choose a future reminder time."
        )

    reminder_id = new_id()

    execute_sql(
        """
        INSERT INTO reminders (
            id,
            user_id,
            title,
            description,
            scheduled_at
        )
        VALUES (
            :id,
            :user_id,
            :title,
            :description,
            :scheduled_at
        )
        """,
        {
            "id": reminder_id,
            "user_id": st.session_state["user_id"],
            "title": title.strip()[:300],
            "description": description,
            "scheduled_at": scheduled_at,
        },
    )

    return reminder_id


def get_reminders():

    return execute_sql(
        """
        SELECT *
        FROM reminders
        WHERE user_id = :user_id
        ORDER BY scheduled_at ASC
        """,
        {
            "user_id": st.session_state["user_id"],
        },
        fetch=True,
    )


def complete_reminder(reminder_id):

    execute_sql(
        """
        UPDATE reminders
        SET completed = TRUE
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": reminder_id,
            "user_id": st.session_state["user_id"],
        },
    )


def delete_reminder(reminder_id):

    execute_sql(
        """
        DELETE FROM reminders
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": reminder_id,
            "user_id": st.session_state["user_id"],
        },
    )


# ------------------------------------------------------------
# WORKSPACE SESSION STATE
# ------------------------------------------------------------

def save_workspace_state(
    workspace,
    state,
):

    execute_sql(
        """
        INSERT INTO workspace_sessions (
            id,
            user_id,
            workspace,
            state_json,
            updated_at
        )
        VALUES (
            :id,
            :user_id,
            :workspace,
            CAST(:state_json AS JSONB),
            NOW()
        )
        ON CONFLICT (user_id, workspace)
        DO UPDATE SET
            state_json = EXCLUDED.state_json,
            updated_at = NOW()
        """,
        {
            "id": new_id(),
            "user_id": st.session_state["user_id"],
            "workspace": workspace,
            "state_json": json.dumps(state),
        },
    )


def load_workspace_state(workspace):

    rows = execute_sql(
        """
        SELECT state_json
        FROM workspace_sessions
        WHERE user_id = :user_id
          AND workspace = :workspace
        LIMIT 1
        """,
        {
            "user_id": st.session_state["user_id"],
            "workspace": workspace,
        },
        fetch=True,
    )

    if not rows:
        return {}

    state = rows[0]["state_json"]

    if isinstance(state, str):
        return json.loads(state)

    return state or {}


# ============================================================
# END OF BLOCK 4
# CONTINUE DIRECTLY WITH BLOCK 5
# ============================================================

# ============================================================
# VINCI AI — BLOCK 5 OF 6
# DEEP RESEARCH, IMAGE STUDIO AND VOICE
# ============================================================

from ddgs import DDGS
from PIL import Image


# ------------------------------------------------------------
# DEEP RESEARCH CONFIGURATION
# ------------------------------------------------------------

RESEARCH_SYSTEM_PROMPT = """
You are Vinci AI Professional Deep Research.

Your task is to produce detailed, structured and
evidence-conscious research.

Requirements:

1. Understand the research question before answering.
2. Use the supplied research material.
3. Separate confirmed information from assumptions.
4. Identify disagreements between sources.
5. Explain limitations and missing evidence.
6. Never invent sources, quotations, statistics or URLs.
7. Use clear professional language.

Organise substantial reports using:

- Research title
- Executive summary
- Research objectives
- Background and context
- Detailed findings
- Evidence and source discussion
- Analysis
- Limitations
- Conclusion
- References
"""


# ------------------------------------------------------------
# WEB SOURCE DISCOVERY
# ------------------------------------------------------------

def search_research_sources(
    query,
    max_results=8,
):

    results = []

    try:

        with DDGS() as search_engine:

            search_results = search_engine.text(
                query,
                max_results=max_results,
            )

            for item in search_results:

                title = item.get("title", "")
                body = item.get("body", "")
                url = item.get("href", "")

                if not title or not url:
                    continue

                results.append({
                    "title": title,
                    "snippet": body,
                    "url": url,
                })

    except Exception as error:

        logger.warning(
            "Research source search failed: %s",
            error,
        )

    return results


# ------------------------------------------------------------
# RESEARCH MATERIAL FORMATTER
# ------------------------------------------------------------

def format_research_sources(sources):

    if not sources:
        return (
            "No external search results were available. "
            "Do not claim that external sources were checked."
        )

    formatted = []

    for index, source in enumerate(
        sources,
        start=1,
    ):

        formatted.append(
            f"""
SOURCE {index}

Title: {source['title']}

Summary:
{source['snippet']}

URL:
{source['url']}
"""
        )

    return "\n\n".join(formatted)


# ------------------------------------------------------------
# PROFESSIONAL RESEARCH WORKFLOW
# ------------------------------------------------------------

def conduct_deep_research(
    research_question,
    use_openrouter=False,
):

    research_question = research_question.strip()

    if len(research_question) < 5:
        raise ValueError(
            "Enter a more detailed research question."
        )

    sources = search_research_sources(
        research_question,
        max_results=8,
    )

    source_material = format_research_sources(
        sources
    )

    research_prompt = f"""
RESEARCH QUESTION:

{research_question}


EXTERNAL RESEARCH MATERIAL:

{source_material}


INSTRUCTIONS:

Prepare a professional research report.

Use the supplied source material carefully.

Reference sources using their supplied titles and URLs.

Do not claim that a source supports a statement unless
the supplied material actually supports that statement.

If the search results are insufficient, state that
additional research is required.
"""

    result = generate_research_answer(
        prompt=research_prompt,
        history=None,
        use_openrouter=use_openrouter,
    )

    result["sources"] = sources

    result["research_question"] = research_question

    return result


# ------------------------------------------------------------
# RESEARCH REPORT SAVING
# ------------------------------------------------------------

def save_research_report(
    question,
    report,
    sources,
):

    source_text = "\n\n".join(
        f"{source['title']}\n{source['url']}"
        for source in sources
    )

    complete_report = (
        report
        + "\n\nREFERENCES\n\n"
        + source_text
    )

    return save_item(
        item_type="research_report",
        title=question[:300],
        content=complete_report,
    )


# ------------------------------------------------------------
# OPENROUTER IMAGE MODEL DISCOVERY
# ------------------------------------------------------------

@st.cache_data(ttl=900)
def get_openrouter_image_models():

    if not OPENROUTER_API_KEY:
        return []

    try:

        response = httpx.get(
            OPENROUTER_MODELS_URL,
            headers={
                "Authorization": (
                    f"Bearer {OPENROUTER_API_KEY}"
                ),
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        available = []

        for item in data.get("data", []):

            pricing = item.get("pricing", {})

            try:

                prompt_price = float(
                    pricing.get("prompt", -1)
                )

                completion_price = float(
                    pricing.get("completion", -1)
                )

            except (ValueError, TypeError):
                continue

            if (
                prompt_price != 0
                or completion_price != 0
            ):
                continue

            architecture = item.get(
                "architecture", {}
            )

            output_modalities = architecture.get(
                "output_modalities", []
            )

            if "image" not in output_modalities:
                continue

            model_id = item.get("id")

            if not model_id:
                continue

            available.append({
                "id": model_id,
                "name": item.get(
                    "name",
                    model_id,
                ),
            })

        return available

    except Exception as error:

        logger.warning(
            "Image model discovery failed: %s",
            error,
        )

        return []


# ------------------------------------------------------------
# IMAGE MODEL VALIDATION
# ------------------------------------------------------------

def validate_free_image_model(model_id):

    if not model_id:
        return False

    models = get_openrouter_image_models()

    return any(
        model["id"] == model_id
        for model in models
    )


# ------------------------------------------------------------
# IMAGE GENERATION
# ------------------------------------------------------------

def generate_vinci_image(
    prompt,
    model=None,
):

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OpenRouter is not configured."
        )

    selected_model = (
        model
        or OPENROUTER_IMAGE_MODEL
    )

    if not selected_model:
        raise RuntimeError(
            "No free image-generation model is configured."
        )

    if not validate_free_image_model(
        selected_model
    ):
        raise RuntimeError(
            "The selected image model is not verified "
            "as a free image-output model. "
            "Paid generation has been blocked."
        )

    payload = {
        "model": selected_model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Create an image based on this description: "
                    + prompt
                ),
            }
        ],
        "modalities": [
            "image",
            "text",
        ],
    }

    response = httpx.post(
        OPENROUTER_CHAT_URL,
        headers={
            "Authorization": (
                f"Bearer {OPENROUTER_API_KEY}"
            ),
            "Content-Type": "application/json",
            "HTTP-Referer": (
                "https://vinci-ai.jteg"
            ),
            "X-Title": "Vinci AI Image Studio",
        },
        json=payload,
        timeout=180,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Image generation failed "
            f"({response.status_code}): "
            f"{response.text[:1000]}"
        )

    data = response.json()

    choices = data.get("choices", [])

    if not choices:
        raise RuntimeError(
            "The image model returned no result."
        )

    message = choices[0].get(
        "message",
        {},
    )

    images = message.get(
        "images",
        [],
    )

    if not images:
        raise RuntimeError(
            "The selected model did not return an image. "
            "Try another supported free image model."
        )

    image_url = (
        images[0]
        .get("image_url", {})
        .get("url", "")
    )

    if not image_url.startswith("data:image/"):
        raise RuntimeError(
            "The returned image format is unsupported."
        )

    try:

        header, encoded_data = image_url.split(
            ",",
            1,
        )

        image_bytes = base64.b64decode(
            encoded_data,
            validate=True,
        )

        image = Image.open(
            io.BytesIO(image_bytes)
        )

        image.verify()

    except Exception as error:

        raise RuntimeError(
            "The generated image could not be validated."
        ) from error

    image_id = new_id()

    image_path = (
        IMAGE_DIRECTORY
        / f"{image_id}.png"
    )

    image_path.write_bytes(image_bytes)

    user_id = st.session_state["user_id"]

    execute_sql(
        """
        INSERT INTO generated_images (
            id,
            user_id,
            prompt,
            image_path,
            model
        )
        VALUES (
            :id,
            :user_id,
            :prompt,
            :image_path,
            :model
        )
        """,
        {
            "id": image_id,
            "user_id": user_id,
            "prompt": prompt,
            "image_path": str(image_path),
            "model": selected_model,
        },
    )

    return {
        "id": image_id,
        "path": str(image_path),
        "model": selected_model,
        "prompt": prompt,
    }


# ------------------------------------------------------------
# IMAGE HISTORY
# ------------------------------------------------------------

def get_generated_images():

    return execute_sql(
        """
        SELECT
            id,
            prompt,
            image_path,
            model,
            created_at
        FROM generated_images
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        """,
        {
            "user_id": st.session_state["user_id"],
        },
        fetch=True,
    )


def delete_generated_image(image_id):

    rows = execute_sql(
        """
        SELECT image_path
        FROM generated_images
        WHERE id = :id
          AND user_id = :user_id
        LIMIT 1
        """,
        {
            "id": image_id,
            "user_id": st.session_state["user_id"],
        },
        fetch=True,
    )

    if not rows:
        return False

    path = Path(rows[0]["image_path"])

    if path.exists():
        path.unlink()

    execute_sql(
        """
        DELETE FROM generated_images
        WHERE id = :id
          AND user_id = :user_id
        """,
        {
            "id": image_id,
            "user_id": st.session_state["user_id"],
        },
    )

    return True


# ------------------------------------------------------------
# IMAGE PROMPT SUGGESTIONS
# ------------------------------------------------------------

IMAGE_PROMPT_CATEGORIES = [
    "Photorealistic product photography",
    "Professional engineering visualization",
    "Architecture and building concepts",
    "Technology and futuristic concepts",
    "Business advertising designs",
    "Scientific illustrations",
    "Nature and landscape photography",
    "Educational diagrams",
    "Industrial machinery concepts",
    "Creative digital artwork",
]


def generate_image_prompt_suggestions(
    category,
):

    prompt = f"""
Generate five distinct, high-quality image prompt ideas
for the following category:

{category}

Each suggestion must be descriptive and suitable
for professional image generation.

Return a numbered list.
"""

    result = generate_chat_answer(
        prompt=prompt,
        history=None,
    )

    return result["text"]


# ------------------------------------------------------------
# SPEECH TRANSCRIPTION
# ------------------------------------------------------------

def transcribe_audio(
    audio_bytes,
    mime_type="audio/wav",
):

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Gemini is not configured for transcription."
        )

    encoded_audio = base64.b64encode(
        audio_bytes
    ).decode("utf-8")

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Transcribe the spoken words "
                            "accurately. Return only the "
                            "transcription. Do not answer "
                            "the speaker's question."
                        )
                    },
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded_audio,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 2048,
        },
    }

    response = httpx.post(
        (
            f"{GEMINI_API_URL}/"
            f"{CHAT_PRIMARY_MODEL}:generateContent"
        ),
        params={
            "key": GEMINI_API_KEY,
        },
        json=payload,
        timeout=120,
    )

    if response.status_code != 200:

        raise RuntimeError(
            "Speech transcription failed: "
            + response.text[:800]
        )

    data = response.json()

    candidates = data.get(
        "candidates",
        [],
    )

    if not candidates:
        raise RuntimeError(
            "No transcription was returned."
        )

    parts = (
        candidates[0]
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
            "The recording could not be transcribed."
        )

    return transcription


# ------------------------------------------------------------
# VOICE CHAT
# ------------------------------------------------------------

def generate_voice_chat_response(
    spoken_text,
):

    result = generate_chat_answer(
        prompt=spoken_text,
        history=None,
    )

    return result


# ------------------------------------------------------------
# TEXT-TO-SPEECH
# ------------------------------------------------------------

def generate_speech_audio(text_to_speak):

    try:
        import edge_tts
    except ImportError:
        raise RuntimeError(
            "Voice playback package is unavailable."
        )

    async def create_audio():

        communicator = edge_tts.Communicate(
            text_to_speak,
            "en-US-AriaNeural",
        )

        audio_data = bytearray()

        async for chunk in communicator.stream():

            if chunk["type"] == "audio":
                audio_data.extend(
                    chunk["data"]
                )

        return bytes(audio_data)

    try:

        return asyncio.run(
            create_audio()
        )

    except RuntimeError as error:

        raise RuntimeError(
            "Voice playback could not start. "
            "Please try again."
        ) from error


# ------------------------------------------------------------
# VOICE RESPONSE PACKAGE
# ------------------------------------------------------------

def create_voice_response(
    spoken_text,
):

    result = generate_voice_chat_response(
        spoken_text
    )

    audio = None

    try:
        audio = generate_speech_audio(
            result["text"]
        )
    except Exception as error:
        logger.warning(
            "Voice playback unavailable: %s",
            error,
        )

    return {
        "text": result["text"],
        "audio": audio,
        "provider": result["provider"],
        "model": result["model"],
    }


# ============================================================
# END OF BLOCK 5
# CONTINUE DIRECTLY WITH BLOCK 6
# ============================================================
# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 6 OF 6
# APPLICATION INTERFACE, DASHBOARD AND WORKSPACES
# ============================================================

import streamlit as st
import inspect
import traceback
from datetime import datetime, timezone


# ============================================================
# 1. APPLICATION STARTUP
# ============================================================

@st.cache_resource(show_spinner="Initializing VINCI AI...")
def vinci_startup():

    initialize_database()
    initialize_extended_database()

    return True


try:
    vinci_startup()

except Exception as e:

    st.error("VINCI AI could not connect to its database.")
    st.code(str(e))
    st.info(
        "Check your DATABASE_URL and PostgreSQL database "
        "configuration before continuing."
    )
    st.stop()


# ============================================================
# 2. INTERFACE CONFIGURATION
# ============================================================

st.markdown("""
<style>

.stApp {
    background: #080D18;
    color: #F4F7FF;
}

section[data-testid="stSidebar"] {
    background: #101827;
    border-right: 1px solid #26344A;
}

section[data-testid="stSidebar"] * {
    color: #EAF0FF;
}

.vinci-brand {
    font-size: 30px;
    font-weight: 900;
    letter-spacing: 3px;
    color: #55B8FF;
}

.vinci-subtitle {
    color: #94A8C5;
    font-size: 12px;
    letter-spacing: 2px;
}

.vinci-card {
    background: linear-gradient(145deg, #17253A, #101827);
    border: 1px solid #263D5B;
    border-radius: 16px;
    padding: 22px;
    min-height: 145px;
    margin-bottom: 12px;
}

.vinci-card h3 {
    color: #FFFFFF;
    margin-bottom: 8px;
}

.vinci-card p {
    color: #A9B9D1;
    font-size: 13px;
}

.vinci-section {
    color: #65BFFF;
    font-weight: 800;
    letter-spacing: 1px;
}

.vinci-footer {
    color: #71839F;
    font-size: 11px;
    text-align: center;
    padding: 20px;
}

div.stButton > button {
    border-radius: 10px;
    border: 1px solid #31577C;
    background: #173451;
    color: white;
    font-weight: 600;
    min-height: 42px;
}

div.stButton > button:hover {
    background: #21649A;
    border-color: #55B8FF;
    color: white;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# 3. SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "vinci_page": "Chat",
    "vinci_authenticated": False,
    "vinci_user": None,
    "vinci_user_id": None,
    "vinci_user_name": None,
    "vinci_user_email": None,
    "vinci_conversation_id": None,
    "vinci_pending_email": None,
    "vinci_chat_input": "",
    "vinci_research_result": None,
    "vinci_image_result": None,
    "vinci_voice_text": None,
}

for key, value in DEFAULT_STATE.items():

    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 4. GENERAL COMPATIBILITY HELPERS
# ============================================================

def vinci_find_function(*names):

    for name in names:

        fn = globals().get(name)

        if callable(fn):
            return fn

    return None


def vinci_call(names, values=None, positional=None):

    if isinstance(names, str):
        names = [names]

    values = values or {}
    positional = positional or []

    fn = vinci_find_function(*names)

    if fn is None:
        raise RuntimeError(
            "Required function not found: " + ", ".join(names)
        )

    try:

        signature = inspect.signature(fn)

        parameters = signature.parameters

        if any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in parameters.values()
        ):
            return fn(**values)

        accepted = {
            key: value
            for key, value in values.items()
            if key in parameters
        }

        required = [
            p for p in parameters.values()
            if p.default == inspect.Parameter.empty
            and p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
        ]

        missing = [
            p.name for p in required
            if p.name not in accepted
        ]

        if missing:
            return fn(*positional)

        return fn(**accepted)

    except (TypeError, ValueError):

        return fn(*positional)


def vinci_get_user_id():

    user = st.session_state.get("vinci_user")

    possible_ids = [
        st.session_state.get("vinci_user_id"),
        st.session_state.get("user_id"),
        st.session_state.get("current_user_id"),
    ]

    if isinstance(user, dict):
        possible_ids.extend([
            user.get("id"),
            user.get("user_id"),
        ])

    for value in possible_ids:

        if value:
            return value

    return None


def vinci_get_user_name():

    user = st.session_state.get("vinci_user")

    possible_names = [
        st.session_state.get("vinci_user_name"),
        st.session_state.get("user_name"),
        st.session_state.get("full_name"),
    ]

    if isinstance(user, dict):
        possible_names.extend([
            user.get("full_name"),
            user.get("name"),
        ])

    for value in possible_names:

        if value:
            return str(value)

    return "User"


def vinci_get_user_email():

    user = st.session_state.get("vinci_user")

    possible_emails = [
        st.session_state.get("vinci_user_email"),
        st.session_state.get("user_email"),
        st.session_state.get("email"),
    ]

    if isinstance(user, dict):
        possible_emails.extend([
            user.get("email"),
        ])

    for value in possible_emails:

        if value:
            return str(value)

    return ""


def vinci_sync_user():

    user_id = vinci_get_user_id()

    if user_id:

        st.session_state["vinci_user_id"] = user_id
        st.session_state["vinci_user_name"] = vinci_get_user_name()
        st.session_state["vinci_user_email"] = vinci_get_user_email()
        st.session_state["vinci_authenticated"] = True

        return True

    return False


def vinci_error(message, error=None):

    st.error(message)

    if error is not None:

        with st.expander("Technical details"):
            st.code(str(error))


# ============================================================
# 5. BRANDING
# ============================================================

def vinci_brand():

    st.markdown(
        """
        <div class="vinci-brand">VINCI AI</div>
        <div class="vinci-subtitle">
        JTEG INTELLIGENCE PLATFORM
        </div>
        """,
        unsafe_allow_html=True
    )


def vinci_footer():

    st.markdown(
        """
        <div class="vinci-footer">
        VINCI AI · POWERED BY JOSIAH TECHNOLOGIES
        AND ENGINEERING GROUP
        <br>
        ENGINEERING INTELLIGENCE FOR THE FUTURE
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# 6. AUTHENTICATION
# ============================================================

def vinci_authentication_page():

    vinci_brand()

    st.markdown("---")

    st.title("Welcome to VINCI AI")

    st.write(
        "Your intelligent workspace for research, "
        "conversation, creativity and innovation."
    )

    login_tab, register_tab, verify_tab = st.tabs([
        "Sign In",
        "Create Account",
        "Verify Email"
    ])

    # --------------------------------------------------------
    # SIGN IN
    # --------------------------------------------------------

    with login_tab:

        st.subheader("Sign in to your account")

        with st.form("vinci_login_form"):

            email = st.text_input(
                "Email address",
                key="vinci_login_email"
            )

            password = st.text_input(
                "Password",
                type="password",
                key="vinci_login_password"
            )

            submit = st.form_submit_button(
                "Sign In",
                use_container_width=True
            )

        if submit:

            if not email or not password:

                st.warning("Enter your email and password.")

            else:

                try:

                    result = authenticate_user(
                        email.strip().lower(),
                        password
                    )

                    if result is False or result is None:

                        st.error(
                            "Login unsuccessful. Check your "
                            "credentials and verification status."
                        )

                    else:

                        vinci_sync_user()

                        if not st.session_state.get(
                            "vinci_authenticated"
                        ):

                            restored = restore_authenticated_session()

                            if restored:
                                vinci_sync_user()

                        if st.session_state.get(
                            "vinci_authenticated"
                        ):

                            st.success("Welcome to VINCI AI.")

                            st.session_state["vinci_page"] = "Chat"

                            st.rerun()

                        else:

                            st.warning(
                                "Authentication was attempted, "
                                "but a user session could not be "
                                "confirmed. Check the authentication "
                                "function's session-state assignments."
                            )

                except Exception as e:

                    vinci_error("Unable to sign in.", e)

    # --------------------------------------------------------
    # REGISTRATION
    # --------------------------------------------------------

    with register_tab:

        st.subheader("Create your VINCI AI account")

        with st.form("vinci_registration_form"):

            full_name = st.text_input("Full name")

            email = st.text_input("Email address")

            phone = st.text_input("Phone number")

            job_description = st.text_input(
                "Occupation / Job description"
            )

            password = st.text_input(
                "Create password",
                type="password"
            )

            confirm_password = st.text_input(
                "Confirm password",
                type="password"
            )

            submit_registration = st.form_submit_button(
                "Create Account",
                use_container_width=True
            )

        if submit_registration:

            if not all([
                full_name,
                email,
                phone,
                job_description,
                password,
                confirm_password
            ]):

                st.warning("Complete all registration fields.")

            elif password != confirm_password:

                st.error("Your passwords do not match.")

            else:

                try:

                    result = register_user(
                        full_name.strip(),
                        email.strip().lower(),
                        phone.strip(),
                        job_description.strip(),
                        password
                    )

                    if result:

                        st.session_state[
                            "vinci_pending_email"
                        ] = email.strip().lower()

                        st.success(
                            "Registration submitted. Check your "
                            "email for your verification code."
                        )

                    else:

                        st.error(
                            "Registration could not be completed. "
                            "Check the information and try again."
                        )

                except Exception as e:

                    vinci_error(
                        "Registration failed.",
                        e
                    )

    # --------------------------------------------------------
    # EMAIL VERIFICATION
    # --------------------------------------------------------

    with verify_tab:

        st.subheader("Verify your email address")

        pending_email = st.session_state.get(
            "vinci_pending_email",
            ""
        )

        verify_email = st.text_input(
            "Registered email",
            value=pending_email,
            key="vinci_verify_email"
        )

        verification_code = st.text_input(
            "Verification code",
            max_chars=6,
            key="vinci_verification_code"
        )

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "Verify Account",
                use_container_width=True
            ):

                if not verify_email or not verification_code:

                    st.warning(
                        "Enter your email and verification code."
                    )

                else:

                    try:

                        result = verify_registration_code(
                            verify_email.strip().lower(),
                            verification_code.strip()
                        )

                        if result:

                            st.success(
                                "Your email has been verified. "
                                "You can now sign in."
                            )

                        else:

                            st.error(
                                "Verification failed. "
                                "Check your code or request another."
                            )

                    except Exception as e:

                        vinci_error(
                            "Verification failed.",
                            e
                        )

        with col2:

            if st.button(
                "Resend Code",
                use_container_width=True
            ):

                if not verify_email:

                    st.warning("Enter your registered email.")

                else:

                    try:

                        result = resend_verification_code(
                            verify_email.strip().lower()
                        )

                        if result:

                            st.success(
                                "A new verification code has "
                                "been requested."
                            )

                        else:

                            st.error(
                                "Unable to resend the verification code."
                            )

                    except Exception as e:

                        vinci_error(
                            "Unable to resend verification code.",
                            e
                        )

    vinci_footer()


# ============================================================
# 7. SESSION RESTORATION
# ============================================================

if not st.session_state.get("vinci_authenticated"):

    try:

        restore_authenticated_session()
        vinci_sync_user()

    except Exception:
        pass


# ============================================================
# 8. CHAT AND CONVERSATION HELPERS
# ============================================================

def vinci_create_new_conversation():

    user_id = vinci_get_user_id()

    if not user_id:
        return None

    try:

        result = vinci_call(
            [
                "create_conversation",
                "new_conversation"
            ],
            {
                "user_id": user_id,
                "title": "New conversation"
            },
            [user_id, "New conversation"]
        )

        if isinstance(result, dict):

            result = (
                result.get("id")
                or result.get("conversation_id")
            )

        st.session_state[
            "vinci_conversation_id"
        ] = result

        return result

    except Exception as e:

        vinci_error(
            "Unable to create a conversation.",
            e
        )

        return None


def vinci_get_messages():

    conversation_id = st.session_state.get(
        "vinci_conversation_id"
    )

    user_id = vinci_get_user_id()

    if not conversation_id or not user_id:
        return []

    try:

        result = vinci_call(
            [
                "read_messages",
                "get_conversation_messages",
                "list_messages"
            ],
            {
                "conversation_id": conversation_id,
                "user_id": user_id
            },
            [conversation_id, user_id]
        )

        return result or []

    except Exception:
        return []


def vinci_save_message(role, content):

    conversation_id = st.session_state.get(
        "vinci_conversation_id"
    )

    user_id = vinci_get_user_id()

    if not conversation_id or not user_id:
        return False

    try:

        vinci_call(
            [
                "save_message",
                "add_message",
                "store_message"
            ],
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": role,
                "content": content,
                "message": content
            },
            [
                conversation_id,
                user_id,
                role,
                content
            ]
        )

        return True

    except Exception as e:

        vinci_error(
            "Message could not be saved.",
            e
        )

        return False


def vinci_chat_page():

    st.title("Chat")

    st.caption(
        "Your intelligent conversation workspace."
    )

    user_id = vinci_get_user_id()

    if not user_id:

        st.warning(
            "Your user session could not be identified. "
            "Please sign in again."
        )

        return

    if not st.session_state.get(
        "vinci_conversation_id"
    ):

        vinci_create_new_conversation()

    messages = vinci_get_messages()

    for message in messages:

        if isinstance(message, dict):

            role = message.get("role", "assistant")
            content = message.get(
                "content",
                message.get("message", "")
            )

        else:

            role = getattr(message, "role", "assistant")
            content = getattr(message, "content", "")

        if role not in ["user", "assistant"]:
            continue

        with st.chat_message(role):

            st.markdown(str(content))

    prompt = st.chat_input(
        "Message VINCI AI..."
    )

    if prompt:

        with st.chat_message("user"):
            st.markdown(prompt)

        history = []

        for message in messages:

            if isinstance(message, dict):

                role = message.get("role")
                content = message.get("content", "")

            else:

                role = getattr(message, "role", None)
                content = getattr(message, "content", "")

            if role in ["user", "assistant"]:

                history.append({
                    "role": role,
                    "content": content
                })

        vinci_save_message("user", prompt)

        with st.chat_message("assistant"):

            with st.spinner("VINCI is thinking..."):

                try# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# BLOCK 6 OF 6
# APPLICATION INTERFACE, DASHBOARD AND WORKSPACES
# ============================================================

import streamlit as st
import inspect
import traceback
from datetime import datetime, timezone


# ============================================================
# 1. APPLICATION STARTUP
# ============================================================

@st.cache_resource(show_spinner="Initializing VINCI AI...")
def vinci_startup():

    initialize_database()
    initialize_extended_database()

    return True


try:
    vinci_startup()

except Exception as e:

    st.error("VINCI AI could not connect to its database.")
    st.code(str(e))
    st.info(
        "Check your DATABASE_URL and PostgreSQL database "
        "configuration before continuing."
    )
    st.stop()


# ============================================================
# 2. INTERFACE CONFIGURATION
# ============================================================

st.markdown("""
<style>

.stApp {
    background: #080D18;
    color: #F4F7FF;
}

section[data-testid="stSidebar"] {
    background: #101827;
    border-right: 1px solid #26344A;
}

section[data-testid="stSidebar"] * {
    color: #EAF0FF;
}

.vinci-brand {
    font-size: 30px;
    font-weight: 900;
    letter-spacing: 3px;
    color: #55B8FF;
}

.vinci-subtitle {
    color: #94A8C5;
    font-size: 12px;
    letter-spacing: 2px;
}

.vinci-card {
    background: linear-gradient(145deg, #17253A, #101827);
    border: 1px solid #263D5B;
    border-radius: 16px;
    padding: 22px;
    min-height: 145px;
    margin-bottom: 12px;
}

.vinci-card h3 {
    color: #FFFFFF;
    margin-bottom: 8px;
}

.vinci-card p {
    color: #A9B9D1;
    font-size: 13px;
}

.vinci-section {
    color: #65BFFF;
    font-weight: 800;
    letter-spacing: 1px;
}

.vinci-footer {
    color: #71839F;
    font-size: 11px;
    text-align: center;
    padding: 20px;
}

div.stButton > button {
    border-radius: 10px;
    border: 1px solid #31577C;
    background: #173451;
    color: white;
    font-weight: 600;
    min-height: 42px;
}

div.stButton > button:hover {
    background: #21649A;
    border-color: #55B8FF;
    color: white;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# 3. SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "vinci_page": "Chat",
    "vinci_authenticated": False,
    "vinci_user": None,
    "vinci_user_id": None,
    "vinci_user_name": None,
    "vinci_user_email": None,
    "vinci_conversation_id": None,
    "vinci_pending_email": None,
    "vinci_chat_input": "",
    "vinci_research_result": None,
    "vinci_image_result": None,
    "vinci_voice_text": None,
}

for key, value in DEFAULT_STATE.items():

    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 4. GENERAL COMPATIBILITY HELPERS
# ============================================================

def vinci_find_function(*names):

    for name in names:

        fn = globals().get(name)

        if callable(fn):
            return fn

    return None


def vinci_call(names, values=None, positional=None):

    if isinstance(names, str):
        names = [names]

    values = values or {}
    positional = positional or []

    fn = vinci_find_function(*names)

    if fn is None:
        raise RuntimeError(
            "Required function not found: " + ", ".join(names)
        )

    try:

        signature = inspect.signature(fn)

        parameters = signature.parameters

        if any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in parameters.values()
        ):
            return fn(**values)

        accepted = {
            key: value
            for key, value in values.items()
            if key in parameters
        }

        required = [
            p for p in parameters.values()
            if p.default == inspect.Parameter.empty
            and p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
        ]

        missing = [
            p.name for p in required
            if p.name not in accepted
        ]

        if missing:
            return fn(*positional)

        return fn(**accepted)

    except (TypeError, ValueError):

        return fn(*positional)


def vinci_get_user_id():

    user = st.session_state.get("vinci_user")

    possible_ids = [
        st.session_state.get("vinci_user_id"),
        st.session_state.get("user_id"),
        st.session_state.get("current_user_id"),
    ]

    if isinstance(user, dict):
        possible_ids.extend([
            user.get("id"),
            user.get("user_id"),
        ])

    for value in possible_ids:

        if value:
            return value

    return None


def vinci_get_user_name():

    user = st.session_state.get("vinci_user")

    possible_names = [
        st.session_state.get("vinci_user_name"),
        st.session_state.get("user_name"),
        st.session_state.get("full_name"),
    ]

    if isinstance(user, dict):
        possible_names.extend([
            user.get("full_name"),
            user.get("name"),
        ])

    for value in possible_names:

        if value:
            return str(value)

    return "User"


def vinci_get_user_email():

    user = st.session_state.get("vinci_user")

    possible_emails = [
        st.session_state.get("vinci_user_email"),
        st.session_state.get("user_email"),
        st.session_state.get("email"),
    ]

    if isinstance(user, dict):
        possible_emails.extend([
            user.get("email"),
        ])

    for value in possible_emails:

        if value:
            return str(value)

    return ""


def vinci_sync_user():

    user_id = vinci_get_user_id()

    if user_id:

        st.session_state["vinci_user_id"] = user_id
        st.session_state["vinci_user_name"] = vinci_get_user_name()
        st.session_state["vinci_user_email"] = vinci_get_user_email()
        st.session_state["vinci_authenticated"] = True

        return True

    return False


def vinci_error(message, error=None):

    st.error(message)

    if error is not None:

        with st.expander("Technical details"):
            st.code(str(error))


# ============================================================
# 5. BRANDING
# ============================================================

def vinci_brand():

    st.markdown(
        """
        <div class="vinci-brand">VINCI AI</div>
        <div class="vinci-subtitle">
        JTEG INTELLIGENCE PLATFORM
        </div>
        """,
        unsafe_allow_html=True
    )


def vinci_footer():

    st.markdown(
        """
        <div class="vinci-footer">
        VINCI AI · POWERED BY JOSIAH TECHNOLOGIES
        AND ENGINEERING GROUP
        <br>
        ENGINEERING INTELLIGENCE FOR THE FUTURE
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# 6. AUTHENTICATION
# ============================================================

def vinci_authentication_page():

    vinci_brand()

    st.markdown("---")

    st.title("Welcome to VINCI AI")

    st.write(
        "Your intelligent workspace for research, "
        "conversation, creativity and innovation."
    )

    login_tab, register_tab, verify_tab = st.tabs([
        "Sign In",
        "Create Account",
        "Verify Email"
    ])

    # --------------------------------------------------------
    # SIGN IN
    # --------------------------------------------------------

    with login_tab:

        st.subheader("Sign in to your account")

        with st.form("vinci_login_form"):

            email = st.text_input(
                "Email address",
                key="vinci_login_email"
            )

            password = st.text_input(
                "Password",
                type="password",
                key="vinci_login_password"
            )

            submit = st.form_submit_button(
                "Sign In",
                use_container_width=True
            )

        if submit:

            if not email or not password:

                st.warning("Enter your email and password.")

            else:

                try:

                    result = authenticate_user(
                        email.strip().lower(),
                        password
                    )

                    if result is False or result is None:

                        st.error(
                            "Login unsuccessful. Check your "
                            "credentials and verification status."
                        )

                    else:

                        vinci_sync_user()

                        if not st.session_state.get(
                            "vinci_authenticated"
                        ):

                            restored = restore_authenticated_session()

                            if restored:
                                vinci_sync_user()

                        if st.session_state.get(
                            "vinci_authenticated"
                        ):

                            st.success("Welcome to VINCI AI.")

                            st.session_state["vinci_page"] = "Chat"

                            st.rerun()

                        else:

                            st.warning(
                                "Authentication was attempted, "
                                "but a user session could not be "
                                "confirmed. Check the authentication "
                                "function's session-state assignments."
                            )

                except Exception as e:

                    vinci_error("Unable to sign in.", e)

    # --------------------------------------------------------
    # REGISTRATION
    # --------------------------------------------------------

    with register_tab:

        st.subheader("Create your VINCI AI account")

        with st.form("vinci_registration_form"):

            full_name = st.text_input("Full name")

            email = st.text_input("Email address")

            phone = st.text_input("Phone number")

            job_description = st.text_input(
                "Occupation / Job description"
            )

            password = st.text_input(
                "Create password",
                type="password"
            )

            confirm_password = st.text_input(
                "Confirm password",
                type="password"
            )

            submit_registration = st.form_submit_button(
                "Create Account",
                use_container_width=True
            )

        if submit_registration:

            if not all([
                full_name,
                email,
                phone,
                job_description,
                password,
                confirm_password
            ]):

                st.warning("Complete all registration fields.")

            elif password != confirm_password:

                st.error("Your passwords do not match.")

            else:

                try:

                    result = register_user(
                        full_name.strip(),
                        email.strip().lower(),
                        phone.strip(),
                        job_description.strip(),
                        password
                    )

                    if result:

                        st.session_state[
                            "vinci_pending_email"
                        ] = email.strip().lower()

                        st.success(
                            "Registration submitted. Check your "
                            "email for your verification code."
                        )

                    else:

                        st.error(
                            "Registration could not be completed. "
                            "Check the information and try again."
                        )

                except Exception as e:

                    vinci_error(
                        "Registration failed.",
                        e
                    )

    # --------------------------------------------------------
    # EMAIL VERIFICATION
    # --------------------------------------------------------

    with verify_tab:

        st.subheader("Verify your email address")

        pending_email = st.session_state.get(
            "vinci_pending_email",
            ""
        )

        verify_email = st.text_input(
            "Registered email",
            value=pending_email,
            key="vinci_verify_email"
        )

        verification_code = st.text_input(
            "Verification code",
            max_chars=6,
            key="vinci_verification_code"
        )

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "Verify Account",
                use_container_width=True
            ):

                if not verify_email or not verification_code:

                    st.warning(
                        "Enter your email and verification code."
                    )

                else:

                    try:

                        result = verify_registration_code(
                            verify_email.strip().lower(),
                            verification_code.strip()
                        )

                        if result:

                            st.success(
                                "Your email has been verified. "
                                "You can now sign in."
                            )

                        else:

                            st.error(
                                "Verification failed. "
                                "Check your code or request another."
                            )

                    except Exception as e:

                        vinci_error(
                            "Verification failed.",
                            e
                        )

        with col2:

            if st.button(
                "Resend Code",
                use_container_width=True
            ):

                if not verify_email:

                    st.warning("Enter your registered email.")

                else:

                    try:

                        result = resend_verification_code(
                            verify_email.strip().lower()
                        )

                        if result:

                            st.success(
                                "A new verification code has "
                                "been requested."
                            )

                        else:

                            st.error(
                                "Unable to resend the verification code."
                            )

                    except Exception as e:

                        vinci_error(
                            "Unable to resend verification code.",
                            e
                        )

    vinci_footer()


# ============================================================
# 7. SESSION RESTORATION
# ============================================================

if not st.session_state.get("vinci_authenticated"):

    try:

        restore_authenticated_session()
        vinci_sync_user()

    except Exception:
        pass


# ============================================================
# 8. CHAT AND CONVERSATION HELPERS
# ============================================================

def vinci_create_new_conversation():

    user_id = vinci_get_user_id()

    if not user_id:
        return None

    try:

        result = vinci_call(
            [
                "create_conversation",
                "new_conversation"
            ],
            {
                "user_id": user_id,
                "title": "New conversation"
            },
            [user_id, "New conversation"]
        )

        if isinstance(result, dict):

            result = (
                result.get("id")
                or result.get("conversation_id")
            )

        st.session_state[
            "vinci_conversation_id"
        ] = result

        return result

    except Exception as e:

        vinci_error(
            "Unable to create a conversation.",
            e
        )

        return None


def vinci_get_messages():

    conversation_id = st.session_state.get(
        "vinci_conversation_id"
    )

    user_id = vinci_get_user_id()

    if not conversation_id or not user_id:
        return []

    try:

        result = vinci_call(
            [
                "read_messages",
                "get_conversation_messages",
                "list_messages"
            ],
            {
                "conversation_id": conversation_id,
                "user_id": user_id
            },
            [conversation_id, user_id]
        )

        return result or []

    except Exception:
        return []


def vinci_save_message(role, content):

    conversation_id = st.session_state.get(
        "vinci_conversation_id"
    )

    user_id = vinci_get_user_id()

    if not conversation_id or not user_id:
        return False

    try:

        vinci_call(
            [
                "save_message",
                "add_message",
                "store_message"
            ],
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": role,
                "content": content,
                "message": content
            },
            [
                conversation_id,
                user_id,
                role,
                content
            ]
        )

        return True

    except Exception as e:

        vinci_error(
            "Message could not be saved.",
            e
        )

        return False


def vinci_chat_page():

    st.title("Chat")

    st.caption(
        "Your intelligent conversation workspace."
    )

    user_id = vinci_get_user_id()

    if not user_id:

        st.warning(
            "Your user session could not be identified. "
            "Please sign in again."
        )

        return

    if not st.session_state.get(
        "vinci_conversation_id"
    ):

        vinci_create_new_conversation()

    messages = vinci_get_messages()

    for message in messages:

        if isinstance(message, dict):

            role = message.get("role", "assistant")
            content = message.get(
                "content",
                message.get("message", "")
            )

        else:

            role = getattr(message, "role", "assistant")
            content = getattr(message, "content", "")

        if role not in ["user", "assistant"]:
            continue

        with st.chat_message(role):

            st.markdown(str(content))

    prompt = st.chat_input(
        "Message VINCI AI..."
    )

    if prompt:

        with st.chat_message("user"):
            st.markdown(prompt)

        history = []

        for message in messages:

            if isinstance(message, dict):

                role = message.get("role")
                content = message.get("content", "")

            else:

                role = getattr(message, "role", None)
                content = getattr(message, "content", "")

            if role in ["user", "assistant"]:

                history.append({
                    "role": role,
                    "content": content
                })

        vinci_save_message("user", prompt)

        with st.chat_message("assistant"):

            with st.spinner("VINCI is thinking..."):

                try:

                    response = generate_chat_answer(
                        prompt,
                        history
                    )

                    if isinstance(response, dict):

                        response = (
                            response.get("text")
                            or response.get("response")
                            or response.get("content")
                            or str(response)
                        )

                    response = str(response)

                    st.markdown(response)

                    vinci_save_message(
                        "assistant",
                        response
                    )

                except Exception as e:

                    vinci_error(
                        "VINCI could not generate a response.",
                        e
                    )


# ============================================================
# 9. DEEP RESEARCH WORKSPACE
# ============================================================

def vinci_research_page():

    st.title("Deep Research")

    st.caption(
        "Explore topics and generate structured research reports."
    )

    research_topic = st.text_area(
        "What would you like VINCI to research?",
        height=130,
        placeholder="Enter your research topic..."
    )

    if st.button(
        "Start Deep Research",
        use_container_width=True
    ):

        if not research_topic.strip():

            st.warning("Enter a research topic.")

        else:

            with st.spinner(
                "VINCI is researching your topic..."
            ):

                try:

                    result = conduct_deep_research(
                        research_topic.strip()
                    )

                    st.session_state[
                        "vinci_research_result"
                    ] = result

                except Exception as e:

                    vinci_error(
                        "Deep Research encountered an error.",
                        e
                    )

    result = st.session_state.get(
        "vinci_research_result"
    )

    if result:

        st.markdown("---")

        if isinstance(result, dict):

            report = (
                result.get("report")
                or result.get("text")
                or result.get("response")
                or ""
            )

            sources = result.get("sources", [])

        else:

            report = str(result)
            sources = []

        st.subheader("Research Report")

        st.markdown(report)

        if sources:

            st.subheader("Research Sources")

            for index, source in enumerate(sources, 1):

                if isinstance(source, dict):

                    title = source.get(
                        "title",
                        f"Source {index}"
                    )

                    url = source.get("url", "")

                    snippet = source.get("snippet", "")

                    st.markdown(f"**{index}. {title}**")

                    if url:
                        st.markdown(f"[Open source]({url})")

                    if snippet:
                        st.caption(snippet)

                else:

                    st.write(source)

        if st.button("Save Research Report"):

            try:

                vinci_call(
                    [
                        "save_research_report",
                        "save_research"
                    ],
                    {
                        "user_id": vinci_get_user_id(),
                        "report": report,
                        "content": report,
                        "title": research_topic[:100]
                    },
                    [
                        vinci_get_user_id(),
                        report
                    ]
                )

                st.success("Research report saved.")

            except Exception as e:

                vinci_error(
                    "Unable to save research report.",
                    e
                )


# ============================================================
# 10. IMAGE STUDIO
# ============================================================

def vinci_image_page():

    st.title("Image Studio")

    st.caption(
        "Create images using VINCI AI."
    )

    prompt = st.text_area(
        "Describe the image you want to create",
        height=140,
        placeholder=(
            "Describe the subject, style, environment, "
            "lighting and composition..."
        )
    )

    aspect_ratio = st.selectbox(
        "Image format",
        [
            "1:1",
            "16:9",
            "9:16",
            "4:3",
            "3:4"
        ]
    )

    if st.button(
        "Generate Image",
        use_container_width=True
    ):

        if not prompt.strip():

            st.warning("Enter an image description.")

        else:

            with st.spinner(
                "VINCI is creating your image..."
            ):

                try:

                    result = generate_vinci_image(
                        prompt.strip()
                    )

                    st.session_state[
                        "vinci_image_result"
                    ] = result

                except Exception as e:

                    vinci_error(
                        "Image generation failed.",
                        e
                    )

    result = st.session_state.get(
        "vinci_image_result"
    )

    if result:

        st.markdown("---")

        image_path = None

        if isinstance(result, dict):

            image_path = (
                result.get("path")
                or result.get("image_path")
                or result.get("file_path")
            )

            if not image_path:
                image_path = result.get("image")

        elif isinstance(result, str):

            image_path = result

        if image_path:

            try:

                st.image(
                    image_path,
                    caption="Created with VINCI AI",
                    use_container_width=True
                )

            except Exception as e:

                st.warning(
                    "The image was generated, but could not "
                    "be displayed from the returned location."
                )

                st.caption(str(e))

        else:

            st.info(
                "Image generation returned a result, "
                "but no displayable image path was identified."
            )


# ============================================================
# 11. DESIGN STUDIO
# ============================================================

def vinci_design_page():

    st.title("Design Studio")

    st.caption(
        "Create professional design concepts and visual briefs."
    )

    design_type = st.selectbox(
        "Choose a design category",
        [
            "Business Advertisement",
            "Corporate Flyer",
            "Product Advertisement",
            "Logo Concept",
            "Engineering Diagram",
            "Architecture Concept",
            "Social Media Design",
            "Presentation Visual",
            "Other"
        ]
    )

    design_description = st.text_area(
        "Describe your design",
        height=150,
        placeholder=(
            "Explain what you want designed. "
            "Include the text, colors, layout and visual direction."
        )
    )

    if st.button(
        "Create Design",
        use_container_width=True
    ):

        if not design_description.strip():

            st.warning("Describe your design first.")

        else:

            design_prompt = f"""
Create a professional {design_type}.

Design requirements:
{design_description}

Quality requirements:
- Professional visual composition
- Clear typography
- Balanced layout
- Appropriate colors
- High visual quality
- Accurate representation of the requested subject
"""

            with st.spinner(
                "VINCI is preparing your design..."
            ):

                try:

                    result = generate_vinci_image(
                        design_prompt
                    )

                    st.session_state[
                        "vinci_image_result"
                    ] = result

                    st.success(
                        "Your design generation request has completed."
                    )

                    st.rerun()

                except Exception as e:

                    vinci_error(
                        "Design generation failed.",
                        e
                    )


# ============================================================
# 12. LIVE WITH VINCI
# ============================================================

def vinci_live_page():

    st.title("Live with VINCI")

    st.caption(
        "Speak to VINCI using audio input."
    )

    audio_file = st.audio_input(
        "Record your message"
    )

    if audio_file:

        if st.button(
            "Process Voice Message",
            use_container_width=True
        ):

            with st.spinner(
                "VINCI is processing your voice..."
            ):

                try:

                    audio_bytes = audio_file.getvalue()

                    transcript = transcribe_audio(
                        audio_bytes
                    )

                    if isinstance(transcript, dict):

                        transcript = (
                            transcript.get("text")
                            or transcript.get("transcript")
                            or str(transcript)
                        )

                    transcript = str(transcript)

                    st.session_state[
                        "vinci_voice_text"
                    ] = transcript

                    st.subheader("Transcription")

                    st.write(transcript)

                    response = create_voice_response(
                        transcript
                    )

                    if isinstance(response, dict):

                        response_text = (
                            response.get("text")
                            or response.get("response")
                            or ""
                        )

                        audio_output = (
                            response.get("audio")
                            or response.get("audio_bytes")
                        )

                    else:

                        response_text = str(response)
                        audio_output = None

                    if response_text:

                        st.subheader("VINCI's Response")

                        st.markdown(response_text)

                    if audio_output:

                        st.audio(
                            audio_output,
                            format="audio/mpeg"
                        )

                except Exception as e:

                    vinci_error(
                        "Voice processing failed.",
                        e
                    )


# ============================================================
# 13. SAVED WORKSPACE
# ============================================================

def vinci_saved_page():

    st.title("Saved")

    st.caption(
        "Access your saved information and work."
    )

    user_id = vinci_get_user_id()

    try:

        items = vinci_call(
            [
                "get_saved_items",
                "list_saved_items",
                "read_saved_items"
            ],
            {
                "user_id": user_id
            },
            [user_id]
        )

        if not items:

            st.info("You have no saved items yet.")

            return

        for item in items:

            if isinstance(item, dict):

                title = item.get(
                    "title",
                    "Saved item"
                )

                content = item.get(
                    "content",
                    item.get("description", "")
                )

                created = item.get(
                    "created_at",
                    ""
                )

            else:

                title = str(item)
                content = ""
                created = ""

            with st.expander(str(title)):

                if content:
                    st.write(content)

                if created:
                    st.caption(str(created))

    except Exception as e:

        vinci_error(
            "Unable to load saved items.",
            e
        )


# ============================================================
# 14. LIBRARY WORKSPACE
# ============================================================

def vinci_library_page():

    st.title("Library")

    st.caption(
        "Manage your documents and uploaded files."
    )

    uploaded_file = st.file_uploader(
        "Upload a document",
        type=[
            "pdf",
            "docx",
            "txt",
            "md",
            "csv",
            "json",
            "py",
            "html"
        ]
    )

    if uploaded_file:

        if st.button("Upload to Library"):

            try:

                result = vinci_call(
                    [
                        "upload_library_file",
                        "save_library_file",
                        "add_library_file"
                    ],
                    {
                        "user_id": vinci_get_user_id(),
                        "uploaded_file": uploaded_file,
                        "file": uploaded_file,
                        "filename": uploaded_file.name,
                        "file_name": uploaded_file.name,
                        "file_bytes": uploaded_file.getvalue(),
                        "content": uploaded_file.getvalue()
                    },
                    [
                        vinci_get_user_id(),
                        uploaded_file
                    ]
                )

                if result:

                    st.success(
                        "Your document has been uploaded."
                    )

                else:

                    st.warning(
                        "The upload function did not confirm success."
                    )

            except Exception as e:

                vinci_error(
                    "Document upload failed.",
                    e
                )

    st.markdown("---")

    st.subheader("Your Documents")

    try:

        files = vinci_call(
            [
                "get_library_files",
                "list_library_files",
                "read_library_files"
            ],
            {
                "user_id": vinci_get_user_id()
            },
            [vinci_get_user_id()]
        )

        if not files:

            st.info("Your library is currently empty.")

        else:

            for file_item in files:

                if isinstance(file_item, dict):

                    filename = file_item.get(
                        "filename",
                        file_item.get("file_name", "Document")
                    )

                    file_id = file_item.get("id")

                    created = file_item.get(
                        "created_at",
                        ""
                    )

                else:

                    filename = str(file_item)
                    file_id = None
                    created = ""

                with st.expander(str(filename)):

                    if created:
                        st.caption(str(created))

                    if file_id:

                        if st.button(
                            "Delete " + str(filename),
                            key=f"delete_library_{file_id}"
                        ):

                            try:

                                vinci_call(
                                    [
                                        "delete_library_file",
                                        "remove_library_file"
                                    ],
                                    {
                                        "user_id": vinci_get_user_id(),
                                        "file_id": file_id,
                                        "id": file_id
                                    },
                                    [
                                        vinci_get_user_id(),
                                        file_id
                                    ]
                                )

                                st.success("Document deleted.")
                                st.rerun()

                            except Exception as e:

                                vinci_error(
                                    "Unable to delete document.",
                                    e
                                )

    except Exception as e:

        vinci_error(
            "Unable to retrieve library documents.",
            e
        )


# ============================================================
# 15. SCHEDULE WORKSPACE
# ============================================================

def vinci_schedule_page():

    st.title("Schedule")

    st.caption(
        "Manage your reminders and scheduled activities."
    )

    with st.form("vinci_reminder_form"):

        reminder_title = st.text_input(
            "Reminder title"
        )

        reminder_description = st.text_area(
            "Description"
        )

        reminder_date = st.date_input(
            "Reminder date"
        )

        reminder_time = st.time_input(
            "Reminder time"
        )

        submit = st.form_submit_button(
            "Create Reminder",
            use_container_width=True
        )

    if submit:

        if not reminder_title.strip():

            st.warning("Enter a reminder title.")

        else:

            try:

                reminder_datetime = datetime.combine(
                    reminder_date,
                    reminder_time
                ).replace(tzinfo=timezone.utc)

                vinci_call(
                    [
                        "create_reminder",
                        "add_reminder",
                        "save_reminder"
                    ],
                    {
                        "user_id": vinci_get_user_id(),
                        "title": reminder_title,
                        "description": reminder_description,
                        "reminder_time": reminder_datetime,
                        "scheduled_at": reminder_datetime,
                        "due_at": reminder_datetime
                    },
                    [
                        vinci_get_user_id(),
                        reminder_title,
                        reminder_description,
                        reminder_datetime
                    ]
                )

                st.success("Reminder created.")

            except Exception as e:

                vinci_error(
                    "Unable to create reminder.",
                    e
                )

    st.markdown("---")

    st.subheader("Your Reminders")

    try:

        reminders = vinci_call(
            [
                "get_reminders",
                "list_reminders",
                "read_reminders"
            ],
            {
                "user_id": vinci_get_user_id()
            },
            [vinci_get_user_id()]
        )

        if not reminders:

            st.info("You have no reminders.")

        else:

            for reminder in reminders:

                if isinstance(reminder, dict):

                    title = reminder.get(
                        "title",
                        "Reminder"
                    )

                    description = reminder.get(
                        "description",
                        ""
                    )

                    reminder_id = reminder.get("id")

                    reminder_time = reminder.get(
                        "reminder_time",
                        reminder.get("scheduled_at", "")
                    )

                else:

                    title = str(reminder)
                    description = ""
                    reminder_id = None
                    reminder_time = ""

                with st.expander(str(title)):

                    if description:
                        st.write(description)

                    if reminder_time:
                        st.caption(str(reminder_time))

                    if reminder_id:

                        if st.button(
                            "Delete Reminder",
                            key=f"delete_reminder_{reminder_id}"
                        ):

                            try:

                                vinci_call(
                                    [
                                        "delete_reminder",
                                        "remove_reminder"
                                    ],
                                    {
                                        "user_id": vinci_get_user_id(),
                                        "reminder_id": reminder_id,
                                        "id": reminder_id
                                    },
                                    [
                                        vinci_get_user_id(),
                                        reminder_id
                                    ]
                                )

                                st.success("Reminder deleted.")
                                st.rerun()

                            except Exception as e:

                                vinci_error(
                                    "Unable to delete reminder.",
                                    e
                                )

    except Exception as e:

        vinci_error(
            "Unable to load reminders.",
            e
        )


# ============================================================
# 16. ADMIN WORKSPACE
# ============================================================

def vinci_admin_page():

    st.title("Administration")

    user_email = vinci_get_user_email()

    try:

        is_admin = current_user_is_admin()

    except Exception:

        is_admin = False

    if not is_admin:

        st.error(
            "Access denied. Administrator privileges are required."
        )

        return

    st.success("Administrator access confirmed.")

    st.markdown("---")

    st.subheader("Platform Statistics")

    try:

        stats = vinci_call(
            [
                "get_admin_statistics",
                "get_admin_stats",
                "admin_dashboard_statistics"
            ],
            {},
            []
        )

        if isinstance(stats, dict):

            columns = st.columns(3)

            statistic_items = list(stats.items())

            for index, item in enumerate(
                statistic_items[:3]
            ):

                key, value = item

                with columns[index]:

                    st.metric(
                        str(key).replace("_", " ").title(),
                        value
                    )

    except Exception as e:

        st.info(
            "Platform statistics are not available through "
            "the current admin functions."
        )

    st.markdown("---")

    st.subheader("User Management")

    try:

        users = vinci_call(
            [
                "get_admin_user_records",
                "list_admin_users",
                "get_all_users"
            ],
            {},
            []
        )

        if users:

            st.dataframe(
                users,
                use_container_width=True
            )

        else:

            st.info("No user records were returned.")

    except Exception as e:

        vinci_error(
            "Unable to retrieve user records.",
            e
        )

    st.markdown("---")

    st.subheader("Administration Information")

    st.write("Signed in administrator:", user_email)

    st.caption(
        "Administrative operations remain subject to "
        "the authorization checks in the backend."
    )


# ============================================================
# 17. MAIN APPLICATION DASHBOARD
# ============================================================

def vinci_dashboard():

    user_name = vinci_get_user_name()

    vinci_brand()

    st.sidebar.markdown("---")

    st.sidebar.markdown(
        f"### Welcome, {user_name}"
    )

    st.sidebar.caption(
        vinci_get_user_email()
    )

    st.sidebar.markdown("---")

    pages = [
        "Chat",
        "Deep Research",
        "Image Studio",
        "Live with Vinci",
        "Design Studio",
        "Saved",
        "Library",
        "Schedule"
    ]

    try:

        if current_user_is_admin():
            pages.append("Admin")

    except Exception:
        pass

    selected_page = st.sidebar.radio(
        "WORKSPACES",
        pages,
        index=(
            pages.index(st.session_state["vinci_page"])
            if st.session_state["vinci_page"] in pages
            else 0
        ),
        key="vinci_navigation"
    )

    st.session_state["vinci_page"] = selected_page

    st.sidebar.markdown("---")

    if st.sidebar.button(
        "＋ New Chat",
        use_container_width=True
    ):

        st.session_state[
            "vinci_conversation_id"
        ] = None

        vinci_create_new_conversation()

        st.session_state["vinci_page"] = "Chat"

        st.rerun()

    if st.sidebar.button(
        "Sign Out",
        use_container_width=True
    ):

        try:
            logout_user()

        except Exception:
            pass

        for key in [
            "vinci_authenticated",
            "vinci_user",
            "vinci_user_id",
            "vinci_user_name",
            "vinci_user_email",
            "vinci_conversation_id"
        ]:

            st.session_state[key] = (
                False if key == "vinci_authenticated" else None
            )

        st.rerun()

    st.sidebar.markdown("---")

    st.sidebar.caption(
        "VINCI AI · JTEG"
    )

    # --------------------------------------------------------
    # WORKSPACE ROUTING
    # --------------------------------------------------------

    if selected_page == "Chat":

        vinci_chat_page()

    elif selected_page == "Deep Research":

        vinci_research_page()

    elif selected_page == "Image Studio":

        vinci_image_page()

    elif selected_page == "Live with Vinci":

        vinci_live_page()

    elif selected_page == "Design Studio":

        vinci_design_page()

    elif selected_page == "Saved":

        vinci_saved_page()

    elif selected_page == "Library":

        vinci_library_page()

    elif selected_page == "Schedule":

        vinci_schedule_page()

    elif selected_page == "Admin":

        vinci_admin_page()

    vinci_footer()


# ============================================================
# 18. MAIN APPLICATION ENTRY POINT
# ============================================================

if st.session_state.get("vinci_authenticated"):

    if not vinci_sync_user():

        st.session_state["vinci_authenticated"] = False

        vinci_authentication_page()

    else:

        vinci_dashboard()

else:

    vinci_authentication_page()
