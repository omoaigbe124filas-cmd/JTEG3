
# ==========================================================
# PASSWORDS AND EMAIL VERIFICATION
# ==========================================================

def make_password_hash(password):
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12)
    )


def check_password(password, saved_hash):
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            saved_hash
        )
    except Exception:
        return False


def send_email(address, subject, content):
    if not all([
        SMTP_HOST,
        SMTP_USER,
        SMTP_PASSWORD,
        SMTP_FROM
    ]):
        raise RuntimeError(
            "Email service is not configured."
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = address
    message.set_content(content)

    with smtplib.SMTP(
        SMTP_HOST,
        SMTP_PORT,
        timeout=25
    ) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)


def issue_code(email, purpose):
    code = f"{secrets.randbelow(1000000):06d}"

    expiry = (
        utc_now() + timedelta(minutes=10)
    ).isoformat()

    with database() as con:
        con.execute("""
            INSERT INTO verification_codes
            (email,code_hash,purpose,expires_at,attempts)
            VALUES(?,?,?,?,0)

            ON CONFLICT(email) DO UPDATE SET
            code_hash=excluded.code_hash,
            purpose=excluded.purpose,
            expires_at=excluded.expires_at,
            attempts=0
        """, (
            email,
            hash_value(code),
            purpose,
            expiry
        ))

    send_email(
        email,
        "Your Vinci AI security code",
        (
            f"Your verification code is {code}.\n\n"
            "This code expires in 10 minutes.\n"
            "Do not share this code with anyone."
        )
    )


def verify_code(email, code, purpose):
    with database() as con:
        row = con.execute("""
            SELECT * FROM verification_codes
            WHERE email=?
        """, (email,)).fetchone()

        if not row:
            return False

        if row["purpose"] != purpose:
            return False

        if row["attempts"] >= 5:
            con.execute(
                "DELETE FROM verification_codes WHERE email=?",
                (email,)
            )
            return False

        expiry = datetime.fromisoformat(
            row["expires_at"]
        )

        if utc_now() > expiry:
            con.execute(
                "DELETE FROM verification_codes WHERE email=?",
                (email,)
            )
            return False

        if secrets.compare_digest(
            row["code_hash"],
            hash_value(code.strip())
        ):
            con.execute(
                "DELETE FROM verification_codes WHERE email=?",
                (email,)
            )
            return True

        con.execute("""
            UPDATE verification_codes
            SET attempts=attempts+1
            WHERE email=?
        """, (email,))

        return False


# ==========================================================
# BROWSER AUTHENTICATION SESSIONS
# ==========================================================

def create_session(user_id):
    token = secrets.token_urlsafe(48)

    expiry = (
        utc_now() + timedelta(days=SESSION_DAYS)
    ).isoformat()

    with database() as con:
        con.execute("""
            INSERT INTO sessions
            (token_hash,user_id,expires_at,created_at)
            VALUES(?,?,?,?)
        """, (
            hash_value(token),
            user_id,
            expiry,
            timestamp()
        ))

        con.execute("""
            UPDATE users
            SET last_login=?,
                login_count=login_count+1
            WHERE id=?
        """, (timestamp(), user_id))

        con.execute("""
            INSERT INTO usage_events
            (user_id,event,created_at)
            VALUES(?,?,?)
        """, (user_id, "login", timestamp()))

    return token


def get_session_user(token):
    if not token:
        return None

    token_digest = hash_value(token)

    with database() as con:
        row = con.execute("""
            SELECT
                users.id,
                users.full_name,
                users.email,
                users.role,
                sessions.expires_at

            FROM sessions

            JOIN users
            ON users.id=sessions.user_id

            WHERE sessions.token_hash=?
        """, (token_digest,)).fetchone()

        if not row:
            return None

        expiry = datetime.fromisoformat(
            row["expires_at"]
        )

        if utc_now() > expiry:
            con.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (token_digest,)
            )
            return None

        return dict(row)


def revoke_session(token):
    if not token:
        return

    with database() as con:
        con.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (hash_value(token),)
        )


def record_event(user_id, event):
    with database() as con:
        con.execute("""
            INSERT INTO usage_events
            (user_id,event,created_at)
            VALUES(?,?,?)
        """, (
            user_id,
            event,
            timestamp()
        ))


# ==========================================================
# COOKIE CONTROLLER
# ==========================================================

cookie_controller = CookieController()

try:
    browser_token = cookie_controller.get(COOKIE_NAME)
except Exception:
    browser_token = None

if "auth_user" not in st.session_state:
    st.session_state.auth_user = None

if not st.session_state.auth_user and browser_token:
    st.session_state.auth_user = get_session_user(
        browser_token
    )


# ==========================================================
# AUTHENTICATION INTERFACE
# ==========================================================

def authentication_screen():

    st.markdown("""
    <div class="hero">
        <div class="small-label">
            JOSIAH TECHNOLOGIES AND ENGINEERING GROUP
        </div>
        <h1>VINCI AI</h1>
        <h3>JTEG Intelligence Platform</h3>
        <p class="muted">
            Intelligence. Creativity. Engineering.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=140)

    st.caption("Made in Nigeria. Built for the World.")

    login_tab, signup_tab, recovery_tab = st.tabs([
        "Login",
        "Create Account",
        "Forgot Password"
    ])

    # ------------------------------------------------------
    # LOGIN
    # ------------------------------------------------------

    with login_tab:
        with st.form("login_form"):
            email = st.text_input(
                "Email address"
            ).strip().lower()

            password = st.text_input(
                "Password",
                type="password"
            )

            submitted = st.form_submit_button(
                "Login",
                use_container_width=True
            )

        if submitted:
            with database() as con:
                user = con.execute("""
                    SELECT * FROM users WHERE email=?
                """, (email,)).fetchone()

            if (
                user
                and check_password(
                    password,
                    user["password_hash"]
                )
            ):
                if not user["verified"]:
                    st.warning(
                        "Verify your email address before logging in."
                    )
                else:
                    token = create_session(user["id"])

                    cookie_controller.set(
                        COOKIE_NAME,
                        token,
                        max_age=SESSION_DAYS * 86400
                    )

                    st.session_state.auth_user = {
                        "id": user["id"],
                        "full_name": user["full_name"],
                        "email": user["email"],
                        "role": user["role"]
                    }

                    st.rerun()

            else:
                st.error(
                    "Email address or password is incorrect."
                )

    # ------------------------------------------------------
    # REGISTRATION
    # ------------------------------------------------------

    with signup_tab:
        with st.form("signup_form"):
            name = st.text_input("Full name")

            email = st.text_input(
                "Email address",
                key="signup_email"
            ).strip().lower()

            phone = st.text_input("Phone number")
            job = st.text_input("Job description")

            password = st.text_input(
                "Create password",
                type="password"
            )

            confirm = st.text_input(
                "Confirm password",
                type="password"
            )

            submit = st.form_submit_button(
                "Create Account",
                use_container_width=True
            )

        if submit:
            valid_email = re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                email
            )

            valid_password = (
                len(password) >= 10
                and re.search(r"[A-Za-z]", password)
                and re.search(r"\d", password)
            )

            if not all([
                name.strip(),
                email,
                phone.strip(),
                job.strip(),
                password
            ]):
                st.error("Complete all required fields.")

            elif not valid_email:
                st.error("Enter a valid email address.")

            elif not valid_password:
                st.error(
                    "Use at least 10 characters, including "
                    "letters and numbers."
                )

            elif password != confirm:
                st.error("Passwords do not match.")

            else:
                try:
                    with database() as con:
                        existing = con.execute("""
                            SELECT id,verified
                            FROM users WHERE email=?
                        """, (email,)).fetchone()

                        if existing and existing["verified"]:
                            raise ValueError(
                                "Account already exists."
                            )

                        if existing:
                            con.execute("""
                                DELETE FROM users WHERE id=?
                            """, (existing["id"],))

                        role = (
                            "admin"
                            if ADMIN_EMAIL
                            and email == ADMIN_EMAIL
                            else "user"
                        )

                        con.execute("""
                            INSERT INTO users
                            (
                                full_name,email,phone,job,
                                password_hash,verified,
                                role,created_at
                            )
                            VALUES(?,?,?,?,?,0,?,?)
                        """, (
                            name.strip(),
                            email,
                            phone.strip(),
                            job.strip(),
                            make_password_hash(password),
                            role,
                            timestamp()
                        ))

                    issue_code(email, "verify")

                    st.session_state.pending_email = email

                    st.success(
                        "Verification code sent. "
                        "Check your email."
                    )

                except Exception:
                    st.error(
                        "Account creation failed. "
                        "Check the details and email configuration."
                    )

        pending = st.session_state.get("pending_email")

        if pending:
            st.divider()
            st.write(f"Verify: {pending}")

            with st.form("verify_signup"):
                code = st.text_input(
                    "Six-digit verification code",
                    max_chars=6
                )

                verify = st.form_submit_button(
                    "Verify Email"
                )

            if verify:
                if verify_code(
                    pending,
                    code,
                    "verify"
                ):
                    with database() as con:
                        con.execute("""
                            UPDATE users SET verified=1
                            WHERE email=?
                        """, (pending,))

                    st.session_state.pop(
                        "pending_email",
                        None
                    )

                    st.success(
                        "Email verified. You can now log in."
                    )
                    st.rerun()

                else:
                    st.error(
                        "Invalid, expired, or exhausted code."
                    )

    # ------------------------------------------------------
    # PASSWORD RECOVERY
    # ------------------------------------------------------

    with recovery_tab:
        with st.form("reset_request"):
            email = st.text_input(
                "Account email",
                key="recover_email"
            ).strip().lower()

            send = st.form_submit_button(
                "Send Reset Code"
            )

        if send:
            with database() as con:
                exists = con.execute("""
                    SELECT id FROM users
                    WHERE email=? AND verified=1
                """, (email,)).fetchone()

            if exists:
                try:
                    issue_code(email, "reset")
                    st.session_state.reset_email = email
                except Exception:
                    pass

            st.info(
                "If the verified account exists, "
                "a reset code has been sent."
            )

        reset_email = st.session_state.get("reset_email")

        if reset_email:
            with st.form("reset_finish"):
                code = st.text_input(
                    "Reset code",
                    max_chars=6
                )

                new_password = st.text_input(
                    "New password",
                    type="password"
                )

                confirm_password = st.text_input(
                    "Confirm new password",
                    type="password"
                )

                reset = st.form_submit_button(
                    "Reset Password"
                )

            if reset:
                valid = (
                    len(new_password) >= 10
                    and re.search(r"[A-Za-z]", new_password)
                    and re.search(r"\d", new_password)
                    and new_password == confirm_password
                )

                if not valid:
                    st.error(
                        "Check your new password. "
                        "It must meet the password requirements."
                    )

                elif verify_code(
                    reset_email,
                    code,
                    "reset"
                ):
                    with database() as con:
                        con.execute("""
                            UPDATE users
                            SET password_hash=?
                            WHERE email=?
                        """, (
                            make_password_hash(new_password),
                            reset_email
                        ))

                        con.execute("""
                            DELETE FROM sessions
                            WHERE user_id=(
                                SELECT id FROM users WHERE email=?
                            )
                        """, (reset_email,))

                    st.session_state.pop(
                        "reset_email",
                        None
                    )

                    st.success(
                        "Password changed. Please log in again."
                    )

                else:
                    st.error("Invalid or expired reset code.")

    st.stop()


# ==========================================================
# AUTHENTICATION GATE
# ==========================================================

if not st.session_state.auth_user:
    authentication_screen()

USER = st.session_state.auth_user
UID = int(USER["id"])
IS_ADMIN = USER["role"] == "admin"

# ==========================================================
# GEMINI AI ENGINE
# ==========================================================

@st.cache_resource
def get_gemini_client(api_key):
    if not api_key:
        return None

    return genai.Client(api_key=api_key)


def ask_gemini(contents, temperature=0.5):
    client = get_gemini_client(GEMINI_KEY)

    if client is None:
        raise RuntimeError(
            "The AI service is not configured."
        )

    response = client.models.generate_content(
        model=PRIMARY_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=temperature
        )
    )

    record_event(UID, "ai_request")

    return (
        response.text
        or "I could not generate a response."
    )


# ==========================================================
# CONVERSATION STORAGE
# ==========================================================

def create_conversation():
    with database() as con:
        result = con.execute("""
            INSERT INTO conversations
            (user_id,title,created_at,updated_at)
            VALUES(?,?,?,?)
        """, (
            UID,
            "New conversation",
            timestamp(),
            timestamp()
        ))

        return result.lastrowid


def owns_conversation(conversation_id):
    if not conversation_id:
        return False

    with database() as con:
        row = con.execute("""
            SELECT id FROM conversations
            WHERE id=? AND user_id=?
        """, (
            conversation_id,
            UID
        )).fetchone()

    return row is not None


def save_message(conversation_id, role, content):
    if not owns_conversation(conversation_id):
        raise PermissionError(
            "Conversation access denied."
        )

    with database() as con:
        con.execute("""
            INSERT INTO messages
            (conversation_id,role,content,created_at)
            VALUES(?,?,?,?)
        """, (
            conversation_id,
            role,
            content,
            timestamp()
        ))

        con.execute("""
            UPDATE conversations
            SET updated_at=?
            WHERE id=? AND user_id=?
        """, (
            timestamp(),
            conversation_id,
            UID
        ))

        if role == "user":
            count = con.execute("""
                SELECT COUNT(*) AS total
                FROM messages
                WHERE conversation_id=?
            """, (conversation_id,)).fetchone()["total"]

            if count == 1:
                title = safe_text(
                    content.replace("\n", " "),
                    55
                )

                con.execute("""
                    UPDATE conversations
                    SET title=?
                    WHERE id=? AND user_id=?
                """, (
                    title or "New conversation",
                    conversation_id,
                    UID
                ))


def read_messages(conversation_id):
    if not owns_conversation(conversation_id):
        return []

    with database() as con:
        rows = con.execute("""
            SELECT role,content,created_at
            FROM messages
            WHERE conversation_id=?
            ORDER BY id ASC
        """, (conversation_id,)).fetchall()

    return rows


def list_conversations():
    with database() as con:
        return con.execute("""
            SELECT id,title,created_at,updated_at
            FROM conversations
            WHERE user_id=?
            ORDER BY updated_at DESC
        """, (UID,)).fetchall()


def generate_chat_answer(
    conversation_id,
    prompt,
    document="",
    image_data=None,
    image_mime="image/jpeg"
):
    previous = list(
        read_messages(conversation_id)
    )[-30:]

    # The current message has already been saved.
    if (
        previous
        and previous[-1]["role"] == "user"
        and previous[-1]["content"] == prompt
    ):
        previous = previous[:-1]

    history = []

    for message in previous:
        history.append(
            types.Content(
                role=(
                    "user"
                    if message["role"] == "user"
                    else "model"
                ),
                parts=[
                    types.Part.from_text(
                        text=message["content"]
                    )
                ]
            )
        )

    parts = [
        types.Part.from_text(text=prompt)
    ]

    if document:
        parts.append(
            types.Part.from_text(
                text=(
                    "\nDOCUMENT CONTEXT:\n"
                    + document[:MAX_DOCUMENT_CHARS]
                )
            )
        )

    if image_data:
        parts.append(
            types.Part.from_bytes(
                data=image_data,
                mime_type=image_mime
            )
        )

    history.append(
        types.Content(
            role="user",
            parts=parts
        )
    )

    return ask_gemini(history)


# ==========================================================
# DOCUMENT EXTRACTION
# ==========================================================

def extract_document(upload):
    data = upload.getvalue()

    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(
            "The document exceeds the upload size limit."
        )

    filename = upload.name.lower()

    if filename.endswith(".pdf"):
        pdf = PdfReader(io.BytesIO(data))

        content = "\n\n".join(
            page.extract_text() or ""
            for page in pdf.pages
        )

    elif filename.endswith(".docx"):
        document = Document(
            io.BytesIO(data)
        )

        content = "\n".join(
            paragraph.text
            for paragraph in document.paragraphs
        )

    elif filename.endswith(
        (".txt", ".md", ".csv", ".json", ".py")
    ):
        content = data.decode(
            "utf-8",
            errors="replace"
        )

    else:
        raise ValueError(
            "Unsupported document format."
        )

    return content[:MAX_DOCUMENT_CHARS]


# ==========================================================
# IMAGE GENERATION
# ==========================================================

def generate_free_image(prompt, width, height):
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(prompt, safe="")
        + f"?width={width}&height={height}"
        + "&model=flux&nologo=true&safe=true"
    )

    with httpx.Client(
        timeout=180,
        follow_redirects=True
    ) as client:
        response = client.get(url)
        response.raise_for_status()

    image_bytes = response.content

    Image.open(
        io.BytesIO(image_bytes)
    ).verify()

    return image_bytes


def save_generated_image(prompt, image_bytes):
    with database() as con:
        con.execute("""
            INSERT INTO generated_images
            (user_id,prompt,image_data,created_at)
            VALUES(?,?,?,?)
        """, (
            UID,
            prompt,
            sqlite3.Binary(image_bytes),
            timestamp()
        ))


# ==========================================================
# 3D COMPONENT GEOMETRY
# ==========================================================

def add_cuboid(fig, x, y, z, dx, dy, dz, label):
    vertices = [
        [x, y, z],
        [x+dx, y, z],
        [x+dx, y+dy, z],
        [x, y+dy, z],
        [x, y, z+dz],
        [x+dx, y, z+dz],
        [x+dx, y+dy, z+dz],
        [x, y+dy, z+dz]
    ]

    faces = [
        (0, 1, 2), (0, 2, 3),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7)
    ]

    fig.add_trace(
        go.Mesh3d(
            x=[v[0] for v in vertices],
            y=[v[1] for v in vertices],
            z=[v[2] for v in vertices],
            i=[f[0] for f in faces],
            j=[f[1] for f in faces],
            k=[f[2] for f in faces],
            opacity=0.85,
            name=label,
            flatshading=True,
            hovertext=label,
            hoverinfo="text"
        )
    )


def make_component_figure(length, width, height):
    figure = go.Figure()

    add_cuboid(
        figure,
        0, 0, 0,
        length, width, height,
        "Component body"
    )

    figure.update_layout(
        height=520,
        margin=dict(l=0, r=0, t=20, b=0),
        scene=dict(
            aspectmode="data",
            xaxis_title="Length (mm)",
            yaxis_title="Width (mm)",
            zaxis_title="Height (mm)",
            camera=dict(
                eye=dict(x=1.7, y=1.7, z=1.3)
            )
        )
    )

    return figure

# ==========================================================
# INTERFACE DESIGN
# ==========================================================

st.markdown("""
<style>
@import url(
'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap'
);

.stApp {
    background:
    radial-gradient(
        circle at 15% 5%,
        rgba(20,105,145,.20),
        transparent 38%
    ),
    linear-gradient(
        135deg,
        #091321,
        #101e31,
        #0b1725
    );
    background-attachment: fixed;
    font-family: 'DM Sans', sans-serif;
}

[data-testid="stSidebar"] {
    background: #091421;
    border-right: 1px solid rgba(70,190,220,.2);
}

h1, h2, h3 {
    font-family: 'Space Grotesk', sans-serif;
}

.stButton button,
.stDownloadButton button {
    border-radius: 11px;
    border: 1px solid rgba(53,216,239,.45);
    background: linear-gradient(110deg,#116b99,#2856a9);
    color: white;
    font-weight: 600;
    min-height: 40px;
}

[data-testid="stChatMessage"] {
    border-radius: 15px;
    border: 1px solid rgba(100,200,240,.12);
    background: rgba(255,255,255,.035);
}

.hero {
    padding: 17px 20px;
    border: 1px solid rgba(70,200,230,.3);
    border-radius: 17px;
    background: linear-gradient(
        120deg,
        rgba(14,107,143,.25),
        rgba(29,56,105,.22)
    );
}

.muted {
    color: #9bb4c9;
}

.small-label {
    color: #8fb4ce;
    font-size: 12px;
    letter-spacing: 2px;
}

</style>
""", unsafe_allow_html=True)


# ==========================================================
# USER WORKSPACE STATE
# ==========================================================

DEFAULTS = {
    "page": "Chat",
    "conversation_id": None,
    "document_context": "",
    "chat_image": None,
    "chat_image_mime": "image/jpeg",
    "chat_uploaded_document_name": None
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ==========================================================
# NAVIGATION
# ==========================================================

PAGES = [
    "Chat",
    "Voice",
    "Image Studio",
    "Design Studio",
    "Images",
    "Library",
    "Projects",
    "Scheduled Reminders",
    "Plugins",
    "Settings",
    "Conversation History"
]

if IS_ADMIN:
    PAGES.append("Database Management")

with st.sidebar:
    st.markdown("## 🤖 VINCI AI")
    st.caption("JTEG INTELLIGENCE PLATFORM")

    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=115)

    st.write(
        f"Welcome, {USER['full_name']}"
    )

    st.caption(APP_VERSION)

    if st.button(
        "＋ New conversation",
        use_container_width=True
    ):
        st.session_state.conversation_id = None
        st.session_state.document_context = ""
        st.session_state.chat_image = None
        st.session_state.page = "Chat"
        st.rerun()

    st.divider()

    selected_page = st.radio(
        "Workspace",
        PAGES,
        index=(
            PAGES.index(st.session_state.page)
            if st.session_state.page in PAGES
            else 0
        ),
        key="workspace_navigation"
    )

    st.session_state.page = selected_page

    st.divider()

    st.caption("ACCOUNT")

    if st.button(
        "Log out",
        use_container_width=True
    ):
        revoke_session(browser_token)

        cookie_controller.remove(COOKIE_NAME)

        st.session_state.auth_user = None
        st.session_state.conversation_id = None

        st.rerun()

    st.caption(
        "Made in Nigeria. Built for the World."
    )


# ==========================================================
# ACTIVE PAGE
# ==========================================================

page = st.session_state.page


# ==========================================================
# CHAT WORKSPACE
# ==========================================================

if page == "Chat":

    st.markdown("""
    <div class="hero">
        <div class="small-label">JTEG INTELLIGENCE PLATFORM</div>
        <h2>VINCI AI</h2>
        <span class="muted">
            What would you like to work on today?
        </span>
    </div>
    """, unsafe_allow_html=True)

    conversations = list_conversations()

    if conversations:
        conversation_options = {
            f"{row['title']} · {row['created_at'][:10]}":
            row["id"]
            for row in conversations
        }

        labels = list(conversation_options.keys())

        current_id = st.session_state.conversation_id

        default_index = 0

        for index, label in enumerate(labels):
            if conversation_options[label] == current_id:
                default_index = index
                break

        selected_label = st.selectbox(
            "Your conversations",
            labels,
            index=default_index,
            key="chat_conversation_selector"
        )

        selected_id = conversation_options[selected_label]

        if selected_id != current_id:
            st.session_state.conversation_id = selected_id
            st.rerun()

    if st.session_state.conversation_id is None:
        st.session_state.conversation_id = create_conversation()

    cid = st.session_state.conversation_id

    if not owns_conversation(cid):
        cid = create_conversation()
        st.session_state.conversation_id = cid

    # Display saved conversation messages.
    for message in read_messages(cid):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Attachments remain separate from the message area.
    with st.expander(
        "＋ Attach an image or document",
        expanded=False
    ):
        uploaded_image = st.file_uploader(
            "Image attachment",
            type=["png", "jpg", "jpeg", "webp"],
            key="chat_image_uploader"
        )

        uploaded_document = st.file_uploader(
            "Document attachment",
            type=["pdf", "docx", "txt", "md", "csv"],
            key="chat_document_uploader"
        )

        if uploaded_image:
            image_bytes = uploaded_image.getvalue()

            if len(image_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
                st.error("Image exceeds the upload size limit.")
                st.session_state.chat_image = None
            else:
                st.session_state.chat_image = image_bytes
                st.session_state.chat_image_mime = (
                    uploaded_image.type
                )

                st.image(
                    image_bytes,
                    caption="Image ready to attach",
                    width=180
                )

        if uploaded_document:
            try:
                st.session_state.document_context = (
                    extract_document(uploaded_document)
                )

                st.session_state.chat_uploaded_document_name = (
                    uploaded_document.name
                )

                st.success("Document ready for this conversation.")

            except Exception:
                st.error("The document could not be read.")

        if st.button("Clear attachments"):
            st.session_state.document_context = ""
            st.session_state.chat_image = None
            st.session_state.chat_uploaded_document_name = None
            st.rerun()

    if st.session_state.chat_uploaded_document_name:
        st.caption(
            "Attached document: "
            + st.session_state.chat_uploaded_document_name
        )

    # Chat input
    prompt = st.chat_input("Message Vinci AI")

    if prompt:
        prompt = safe_text(prompt, 12000)

        image_bytes = st.session_state.chat_image
        image_mime = st.session_state.chat_image_mime
        document_context = st.session_state.document_context

        try:
            save_message(cid, "user", prompt)

            with st.chat_message("user"):
                st.markdown(prompt)

                if image_bytes:
                    st.caption("Image attached")

                if document_context:
                    st.caption("Document context attached")

            with st.chat_message("assistant"):
                with st.spinner("Vinci AI is thinking..."):
                    answer = generate_chat_answer(
                        cid,
                        prompt,
                        document_context,
                        image_bytes,
                        image_mime
                    )

                st.markdown(answer)

            save_message(cid, "assistant", answer)

            st.session_state.chat_image = None
            st.session_state.document_context = ""
            st.session_state.chat_uploaded_document_name = None

            st.rerun()

        except Exception:
            st.error(
                "Vinci AI could not complete the request. "
                "Please check the AI service configuration "
                "and try again."
            )


# ==========================================================
# VOICE WORKSPACE
# ==========================================================

elif page == "Voice":

    st.subheader("Voice Workspace")

    st.write(
        "Convert written text into spoken audio."
    )

    voice_text = st.text_area(
        "Enter text",
        height=180
    )

    if st.button("Generate voice"):
        if not edge_tts:
            st.error(
                "Voice generation is not available. "
                "Check the installed requirements."
            )

        elif not voice_text.strip():
            st.warning("Enter text first.")

        else:
            async def create_audio():
                communicator = edge_tts.Communicate(
                    voice_text,
                    "en-US-AriaNeural"
                )

                audio_data = bytearray()

                async for chunk in communicator.stream():
                    if chunk["type"] == "audio":
                        audio_data.extend(chunk["data"])

                return bytes(audio_data)

            try:
                with st.spinner("Generating audio..."):
                    audio = asyncio.run(create_audio())

                st.audio(audio, format="audio/mp3")

                st.download_button(
                    "Download audio",
                    audio,
                    "vinci_voice.mp3",
                    "audio/mpeg"
                )

            except Exception:
                st.error(
                    "Voice generation failed. "
                    "Please try again later."
    )
    # ==========================================================
# IMAGE STUDIO
# ==========================================================

elif page == "Image Studio":

    st.subheader("Image Studio")

    st.write(
        "Create visual concepts and illustrations "
        "from your written descriptions."
    )

    image_prompt = st.text_area(
        "Describe the image you want to create",
        height=150,
        placeholder=(
            "Example: A futuristic Nigerian electric vehicle "
            "designed for modern African cities..."
        ),
        key="image_studio_prompt"
    )

    image_style = st.selectbox(
        "Image style",
        [
            "Photorealistic",
            "3D Render",
            "Digital Art",
            "Engineering Concept",
            "Cinematic",
            "Illustration"
        ]
    )

    image_ratio = st.selectbox(
        "Image dimensions",
        [
            "1024x1024",
            "1024x1536",
            "1536x1024"
        ]
    )

    if st.button(
        "Generate image",
        use_container_width=True
    ):

        if not image_prompt.strip():
            st.warning("Please describe the image first.")

        else:
            full_prompt = (
                image_prompt.strip()
                + ", "
                + image_style
                + " style, high quality, detailed composition"
            )

            try:
                import urllib.parse

                encoded_prompt = urllib.parse.quote(
                    full_prompt,
                    safe=""
                )

                width, height = map(
                    int,
                    image_ratio.split("x")
                )

                image_url = (
                    "https://image.pollinations.ai/prompt/"
                    + encoded_prompt
                    + f"?width={width}&height={height}"
                    + "&nologo=true"
                )

                with st.spinner(
                    "Preparing your image..."
                ):

                    response = httpx.get(
                        image_url,
                        timeout=120,
                        follow_redirects=True
                    )

                    response.raise_for_status()

                    generated_image = response.content

                    if not generated_image:
                        raise ValueError(
                            "The image service returned no image."
                        )

                st.image(
                    generated_image,
                    caption="Generated with Vinci AI",
                    use_container_width=True
                )

                st.download_button(
                    "Download image",
                    data=generated_image,
                    file_name="vinci_generated_image.png",
                    mime="image/png",
                    use_container_width=True
                )

            except Exception:
                st.error(
                    "Image generation is temporarily unavailable. "
                    "Please try again later."
                )


# ==========================================================
# DESIGN STUDIO
# ==========================================================

elif page == "Design Studio":

    st.subheader("Engineering Design Studio")

    st.write(
        "Explore engineering concepts, component arrangements, "
        "3D visualisations and photo-based design analysis."
    )

    design_mode = st.selectbox(
        "Select a design workspace",
        [
            "2D Design Concepts",
            "3D Component Visualisation",
            "Photo-to-Design",
            "Exploded View Analysis"
        ],
        key="design_mode"
    )

    # ------------------------------------------------------
    # 2D DESIGN CONCEPTS
    # ------------------------------------------------------

    if design_mode == "2D Design Concepts":

        st.markdown("### 2D Design Concepts")

        design_description = st.text_area(
            "Describe the engineering design",
            height=140,
            placeholder=(
                "Describe the machine, product, equipment "
                "or engineering system you want to design."
            )
        )

        if st.button("Develop design concept"):

            if not design_description.strip():
                st.warning("Enter a design description.")

            else:
                request = f"""
You are an engineering design assistant.

Develop a conceptual 2D engineering design brief.

User's description:
{design_description}

Provide:
1. Design overview.
2. Main components.
3. Component functions.
4. Suggested arrangement.
5. Materials to investigate.
6. Important dimensions that must be confirmed.
7. Safety and engineering considerations.
8. Suggested next design stage.

Do not invent verified dimensions.
Clearly identify assumptions.
This is a conceptual design, not a certified engineering drawing.
"""

                try:
                    with st.spinner(
                        "Developing engineering concept..."
                    ):
                        result = ask_gemini(request)

                    st.markdown(result)

                except Exception:
                    st.error(
                        "The design concept could not be generated."
                    )

    # ------------------------------------------------------
    # 3D COMPONENT VISUALISATION
    # ------------------------------------------------------

    elif design_mode == "3D Component Visualisation":

        st.markdown("### 3D Component Visualisation")

        st.caption(
            "Create a simple interactive 3D conceptual component."
        )

        component_name = st.text_input(
            "Component name",
            value="Engineering Component"
        )

        length = st.number_input(
            "Length",
            min_value=0.1,
            max_value=1000.0,
            value=10.0
        )

        width = st.number_input(
            "Width",
            min_value=0.1,
            max_value=1000.0,
            value=6.0
        )

        height = st.number_input(
            "Height",
            min_value=0.1,
            max_value=1000.0,
            value=4.0
        )

        if st.button("Render 3D component"):

            x = [
                0, length, length, 0,
                0, length, length, 0
            ]

            y = [
                0, 0, width, width,
                0, 0, width, width
            ]

            z = [
                0, 0, 0, 0,
                height, height, height, height
            ]

            i = [
                0, 0, 4, 4,
                0, 0, 1, 1,
                2, 2, 3, 3
            ]

            j = [
                1, 2, 5, 6,
                1, 5, 2, 6,
                3, 7, 0, 4
            ]

            k = [
                2, 3, 6, 7,
                5, 4, 6, 5,
                7, 6, 4, 7
            ]

            fig = go.Figure(
                data=[
                    go.Mesh3d(
                        x=x,
                        y=y,
                        z=z,
                        i=i,
                        j=j,
                        k=k,
                        opacity=0.85,
                        flatshading=True,
                        name=component_name
                    )
                ]
            )

            fig.update_layout(
                title=component_name,
                scene=dict(
                    xaxis_title="Length",
                    yaxis_title="Width",
                    zaxis_title="Height",
                    aspectmode="data",
                    camera=dict(
                        eye=dict(x=1.6, y=1.6, z=1.2)
                    )
                ),
                margin=dict(
                    l=0,
                    r=0,
                    t=45,
                    b=0
                ),
                height=550
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

            st.info(
                "This is a basic cuboid visualisation. "
                "It is not a manufacturing-ready CAD model."
            )

    # ------------------------------------------------------
    # PHOTO-TO-DESIGN
    # ------------------------------------------------------

    elif design_mode == "Photo-to-Design":

        st.markdown("### Photo-to-Design")

        st.write(
            "Upload a photograph of a machine, component "
            "or engineering assembly for visual analysis."
        )

        design_photo = st.file_uploader(
            "Upload engineering photograph",
            type=["png", "jpg", "jpeg", "webp"],
            key="photo_to_design_upload"
        )

        confirmed_dimensions = st.text_area(
            "Known dimensions (optional)",
            placeholder=(
                "Enter any dimensions you have measured. "
                "For example: overall length 20 cm."
            )
        )

        if design_photo:

            photo_bytes = design_photo.getvalue()

            if len(photo_bytes) > MAX_UPLOAD_MB * 1024 * 1024:

                st.error(
                    "The uploaded photograph exceeds the "
                    "maximum file size."
                )

            else:

                st.image(
                    photo_bytes,
                    caption="Uploaded engineering photograph",
                    use_container_width=True
                )

                if st.button(
                    "Analyse photograph",
                    use_container_width=True
                ):

                    photo_request = f"""
You are Vinci AI's engineering design analysis assistant.

Analyse the supplied engineering photograph.

Known dimensions supplied by the user:
{confirmed_dimensions or "No confirmed dimensions supplied."}

Organise your response into these sections:

1. VISIBLE COMPONENTS
Identify only components that can reasonably be observed.

2. COMPONENT FUNCTIONS
Explain likely functions. Mark uncertain functions as estimates.

3. ASSEMBLY ARRANGEMENT
Explain how visible components appear to relate to one another.

4. DIMENSIONS
Do not invent exact measurements from the photograph.
Identify measurements that need to be taken.

5. HIDDEN COMPONENTS
List any components that may be required but cannot be confirmed
from the photograph. Clearly mark them as hypothetical.

6. RECONSTRUCTION CONCEPT
Describe a possible engineering reconstruction.

7. EXPLODED VIEW PLAN
Describe how the visible components could be separated
for an exploded-view illustration.

8. SAFETY AND VERIFICATION
Identify areas that require inspection and professional
engineering verification.

Never present an estimate as a confirmed observation.
"""

                    try:

                        with st.spinner(
                            "Analysing engineering photograph..."
                        ):

                            analysis_result = ask_gemini(
                                photo_request,
                                image_bytes=photo_bytes,
                                image_mime=design_photo.type
                            )

                        st.markdown(
                            "### Engineering Analysis"
                        )

                        st.markdown(analysis_result)

                        st.warning(
                            "Photograph-based analysis is conceptual. "
                            "Verify dimensions, materials and internal "
                            "construction before manufacturing."
                        )

                    except Exception:

                        st.error(
                            "The photograph could not be analysed. "
                            "Please try again."
                        )

    # ------------------------------------------------------
    # EXPLODED VIEW ANALYSIS
    # ------------------------------------------------------

    elif design_mode == "Exploded View Analysis":

        st.markdown("### Exploded View Analysis")

        st.write(
            "Describe an assembly to develop a conceptual "
            "exploded-view component arrangement."
        )

        assembly_description = st.text_area(
            "Describe the assembly",
            height=130,
            placeholder=(
                "Example: A small electric motor consisting of "
                "a casing, shaft, rotor, stator, bearings and cover."
            )
        )

        if st.button("Analyse assembly"):

            if not assembly_description.strip():

                st.warning(
                    "Describe the assembly first."
                )

            else:

                exploded_request = f"""
You are an engineering assembly analysis assistant.

Assembly description:
{assembly_description}

Provide:

1. Assembly overview.
2. A numbered list of components.
3. The function of each component.
4. The likely assembly sequence.
5. A conceptual exploded-view arrangement.
6. Interfaces and connection points.
7. Components that require confirmed dimensions.
8. Areas requiring engineering verification.

Do not invent exact dimensions.
Distinguish visible or supplied information from estimates.
Do not claim that a conceptual arrangement is a verified design.
"""

                try:

                    with st.spinner(
                        "Analysing assembly..."
                    ):

                        exploded_result = ask_gemini(
                            exploded_request
                        )

                    st.markdown(exploded_result)

                except Exception:

                    st.error(
                        "Assembly analysis could not be completed."
                    )


# ==========================================================
# IMAGES PAGE
# ==========================================================

elif page == "Images":

    st.subheader("Images")

    st.write(
        "Generate images in Image Studio and download "
        "the results to your device."
    )

    st.info(
        "This page does not currently provide a permanent "
        "cloud image gallery."
    )


# ==========================================================
# LIBRARY PAGE
# ==========================================================

elif page == "Library":

    st.subheader("Personal Library")

    st.write(
        "Your personal workspace for organising project "
        "information and saved notes."
    )

    library_title = st.text_input(
        "Note title",
        key="library_title"
    )

    library_content = st.text_area(
        "Write a note",
        height=180,
        key="library_content"
    )

    if st.button("Save note"):

        if not library_title.strip() or not library_content.strip():

            st.warning(
                "Enter both a title and note content."
            )

        else:

            try:

                with sqlite3.connect(
                    str(Path("vinci_data") / "vinci.sqlite3")
                ) as conn:

                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS library_notes (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            title TEXT NOT NULL,
                            content TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                        """
                    )

                    conn.execute(
                        """
                        INSERT INTO library_notes
                        (user_id, title, content, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            USER["id"],
                            safe_text(library_title, 200),
                            safe_text(library_content, 20000),
                            datetime.now(timezone.utc).isoformat()
                        )
                    )

                    conn.commit()

                st.success("Your note has been saved.")

                st.rerun()

            except Exception:

                st.error(
                    "The note could not be saved."
                )

    st.divider()

    st.markdown("### Saved notes")

    try:

        with sqlite3.connect(
            str(Path("vinci_data") / "vinci.sqlite3")
        ) as conn:

            conn.row_factory = sqlite3.Row

            notes = conn.execute(
                """
                SELECT id, title, content, created_at
                FROM library_notes
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (USER["id"],)
            ).fetchall()

        if notes:

            for note in notes:

                with st.expander(note["title"]):

                    st.write(note["content"])

                    st.caption(note["created_at"])

                    if st.button(
                        "Delete note",
                        key=f"delete_note_{note['id']}"
                    ):

                        with sqlite3.connect(
                            str(Path("vinci_data") / "vinci.sqlite3")
                        ) as conn:

                            conn.execute(
                                """
                                DELETE FROM library_notes
                                WHERE id = ? AND user_id = ?
                                """,
                                (
                                    note["id"],
                                    USER["id"]
                                )
                            )

                            conn.commit()

                        st.rerun()

        else:

            st.info("You have not saved any notes yet.")

    except Exception:

        st.error(
            "The library could not be loaded."
    )
