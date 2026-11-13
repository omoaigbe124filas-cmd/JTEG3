
import streamlit as st
import sqlite3
import os
import io
import asyncio
import httpx
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image
from google import genai
from google.genai import types

from pypdf import PdfReader
from docx import Document

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    import plotly.graph_objects as go
except ImportError:
    go = None

try:
    import trimesh
except ImportError:
    trimesh = None

try:
    import ezdxf
except ImportError:
    ezdxf = None


# ============================================================
# VINCI AI — JTEG INTELLIGENCE PLATFORM
# ============================================================

st.set_page_config(
    page_title="Vinci AI | JTEG Intelligence Platform",
    page_icon="🤖",
    layout="wide"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;800&family=Space+Grotesk:wght@500;700&display=swap');

.stApp {
    background:
    radial-gradient(circle at 10% 10%, #123c60, transparent 40%),
    radial-gradient(circle at 90% 90%, #07545c, transparent 40%),
    linear-gradient(140deg,#06101f,#0c2340,#071b2b);
    background-attachment: fixed;
}
[data-testid="stSidebar"] {
    background: #071526;
    border-right: 1px solid #164d65;
}
h1,h2,h3 {
    font-family: 'Space Grotesk',sans-serif;
}
.stButton button,.stDownloadButton button {
    border-radius: 12px;
    background: linear-gradient(100deg,#087da9,#315fd5);
    color: white;
    border: 1px solid #40d9f5;
    font-weight: 700;
}
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,.055);
    border: 1px solid rgba(100,220,255,.18);
    border-radius: 15px;
}
.hero {
    padding: 25px;
    border-radius: 22px;
    border: 1px solid #24627b;
    background: linear-gradient(120deg,rgba(0,130,170,.25),rgba(30,50,100,.4));
}
.kicker {
    color: #55e6ff;
    letter-spacing: 3px;
    font-size: 11px;
    font-weight: 800;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# CONFIGURATION
# ============================================================

def get_secret(name):
    try:
        return st.secrets.get(name, os.getenv(name, ""))
    except Exception:
        return os.getenv(name, "")


GEMINI_KEY = get_secret("GEMINI_API_KEY")

CHAT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro"
]

SYSTEM_PROMPT = """
You are Vinci AI, the engineering research and learning assistant
of JTEG — Josiah Technologies and Engineering Group.

Your platform name is JTEG Intelligence Platform.

Your responsibilities:
- Engineering education and research.
- Technical explanations and calculations.
- Software and programming assistance.
- Engineering documentation.
- Product and component concept development.
- Mathematics, physics and technical analysis.
- CAD and design workflow guidance.

Be accurate and structured.
Explain assumptions and units.
Never invent research sources or test results.
Distinguish estimates from verified facts.
Do not claim to have simulated or physically tested a design
unless an actual simulation or test was performed.

For high-risk electrical, machinery and other hazardous subjects,
keep explanations educational and safety-focused. Do not give
dangerous hands-on construction or live-testing instructions.
Recommend qualified professional supervision.
"""


def gemini_client():
    if not GEMINI_KEY:
        raise ValueError(
            "GEMINI_API_KEY is missing. Add it to Streamlit Secrets."
        )
    return genai.Client(api_key=GEMINI_KEY)


# ============================================================
# SQLITE DATABASE
# ============================================================

DATA_DIR = Path("vinci_data")
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "vinci.sqlite3"


def database():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_database():
    with database() as conn:
        conn.execute("PRAGMA journal_mode=WAL")

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            role TEXT,
            content TEXT,
            created TEXT,
            FOREIGN KEY(conversation_id)
                REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            status TEXT,
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            due TEXT,
            notes TEXT,
            completed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            content TEXT,
            created TEXT
        );
        """)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def new_conversation():
    with database() as conn:
        cur = conn.execute(
            "INSERT INTO conversations(title,created) VALUES(?,?)",
            ("New conversation", timestamp())
        )
        return cur.lastrowid


def save_message(cid, role, content):
    with database() as conn:
        conn.execute(
            """INSERT INTO messages
            (conversation_id,role,content,created)
            VALUES(?,?,?,?)""",
            (cid, role, content, timestamp())
        )

        if role == "user":
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id=?",
                (cid,)
            ).fetchone()[0]

            if count == 1:
                title = content.strip().replace("\n", " ")[:60]
                conn.execute(
                    "UPDATE conversations SET title=? WHERE id=?",
                    (title, cid)
                )


def load_messages(cid):
    with database() as conn:
        return conn.execute(
            """SELECT role,content FROM messages
            WHERE conversation_id=? ORDER BY id""",
            (cid,)
        ).fetchall()


def load_conversations():
    with database() as conn:
        return conn.execute(
            "SELECT * FROM conversations ORDER BY id DESC LIMIT 40"
        ).fetchall()


def delete_conversation(cid):
    with database() as conn:
        conn.execute(
            "DELETE FROM conversations WHERE id=?", (cid,)
        )


initialize_database()


# ============================================================
# DOCUMENT EXTRACTION
# ============================================================

def extract_document(upload):
    name = upload.name.lower()
    data = upload.getvalue()

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        pages = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"PAGE {i+1}\n{text}")

        return "\n\n".join(pages)

    if name.endswith(".docx"):
        doc = Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs]

        for table in doc.tables:
            for row in table.rows:
                paragraphs.append(
                    " | ".join(cell.text for cell in row.cells)
                )

        return "\n".join(paragraphs)

    if name.endswith((".txt", ".md", ".csv", ".py", ".json")):
        return data.decode("utf-8", errors="replace")

    raise ValueError("Unsupported document type.")


# ============================================================
# GEMINI CHAT WITH CONVERSATION HISTORY
# ============================================================

def ask_vinci(cid, prompt, model, document="", research="",
              image_bytes=None, image_mime="image/jpeg"):

    client = gemini_client()

    rows = load_messages(cid)

    history = []

    for row in rows:
        history.append(
            types.Content(
                role="user" if row["role"] == "user" else "model",
                parts=[types.Part.from_text(text=row["content"])]
            )
        )

    if not history:
        history = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)]
            )
        ]

    if history:
        parts = list(history[-1].parts)

        if document:
            parts.append(types.Part.from_text(
                text="\nDOCUMENT REFERENCE:\n" + document[:40000]
            ))

        if research:
            parts.append(types.Part.from_text(
                text="\nRESEARCH RESULTS:\n" + research[:18000]
            ))

        if image_bytes:
            parts.append(types.Part.from_bytes(
                data=image_bytes,
                mime_type=image_mime
            ))

        history[-1] = types.Content(role="user", parts=parts)

    response = client.models.generate_content(
        model=model,
        contents=history[-20:],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.5
        )
    )

    return response.text or "Vinci could not produce a text response."


# ============================================================
# WEB RESEARCH
# ============================================================

def research_web(query, limit=6):
    if DDGS is None:
        raise RuntimeError("Install ddgs to enable research.")

    results = []

    with DDGS() as search:
        for item in search.text(query, max_results=limit):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("href", ""),
                "body": item.get("body", "")
            })

    return results


# ============================================================
# FREE IMAGE GENERATION — NO GEMINI IMAGE BILLING
# ============================================================

def generate_free_image(prompt, width=1024, height=1024):
    """
    Best-effort connection to Pollinations' documented legacy
    image endpoint. No Gemini image-generation API is called.

    Provider availability, authentication and limits can change.
    This is not a guaranteed unlimited free service.
    """

    encoded = urllib.parse.quote(prompt, safe="")

    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}"
        "&model=flux&nologo=true&safe=true"
    )

    with httpx.Client(timeout=180, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "")

    if "image" not in content_type:
        raise RuntimeError(
            "The image service did not return an image. "
            "It may require authentication or may be temporarily unavailable."
        )

    return response.content


# ============================================================
# VOICE
# ============================================================

def transcribe_audio(audio):
    client = gemini_client()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_text(
                text="Transcribe this audio accurately. Return only the words."
            ),
            types.Part.from_bytes(
                data=audio.getvalue(),
                mime_type=audio.type or "audio/wav"
            )
        ]
    )

    return response.text or ""


def make_speech(text):
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed.")

    async def create_audio():
        communicator = edge_tts.Communicate(
            text, "en-NG-AbeoNeural"
        )

        audio = bytearray()

        async for chunk in communicator.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])

        return bytes(audio)

    try:
        return asyncio.run(create_audio())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(create_audio())
        finally:
            loop.close()


# ============================================================
# BASIC ENGINEERING EXPORTS
# ============================================================

def make_stl(length, width, height):
    if trimesh is None:
        raise RuntimeError("Install trimesh.")

    mesh = trimesh.creation.box(
        extents=(length, width, height)
    )

    return mesh.export(file_type="stl")


def make_dxf(length, width):
    if ezdxf is None:
        raise RuntimeError("Install ezdxf.")

    doc = ezdxf.new("R2010")
    model = doc.modelspace()

    model.add_lwpolyline(
        [
            (0, 0),
            (length, 0),
            (length, width),
            (0, width),
            (0, 0)
        ]
    )

    output = io.StringIO()
    doc.write(output)

    return output.getvalue().encode("utf-8")


# ============================================================
# SESSION STATE
# ============================================================

if "cid" not in st.session_state:
    st.session_state.cid = new_conversation()

if "document_context" not in st.session_state:
    st.session_state.document_context = ""

if "research_context" not in st.session_state:
    st.session_state.research_context = ""

if "last_image" not in st.session_state:
    st.session_state.last_image = None


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown("## 🤖 VINCI AI")
    st.caption("JTEG Intelligence Platform")

    if GEMINI_KEY:
        st.success("Gemini connection configured")
    else:
        st.error("Gemini API key missing")

    model = st.selectbox(
        "AI model",
        CHAT_MODELS,
        index=0
    )

    st.divider()

    if st.button("＋ New conversation", use_container_width=True):
        st.session_state.cid = new_conversation()
        st.rerun()

    st.markdown("### Previous conversations")

    for item in load_conversations():

        col1, col2 = st.columns([5, 1])

        with col1:
            if st.button(
                item["title"][:30],
                key=f"open_{item['id']}"
            ):
                st.session_state.cid = item["id"]
                st.rerun()

        with col2:
            if st.button("×", key=f"del_{item['id']}"):
                delete_conversation(item["id"])

                if item["id"] == st.session_state.cid:
                    st.session_state.cid = new_conversation()

                st.rerun()


# ============================================================
# HERO
# ============================================================

st.markdown("""
<div class="hero">
    <div class="kicker">
        JOSIAH TECHNOLOGIES AND ENGINEERING GROUP
    </div>
    <h1 style="font-size:48px;color:white;margin:5px 0">
        Vinci AI
    </h1>
    <h3 style="color:#55e6ff">
        JTEG Intelligence Platform
    </h3>
    <p style="color:#c5d5e2">
        Engineering knowledge. Research. Design. Intelligence.
    </p>
</div>
""", unsafe_allow_html=True)


# ============================================================
# MAIN NAVIGATION
# ============================================================

tabs = st.tabs([
    "💬 CHAT",
    "🔎 RESEARCH",
    "🎙️ VOICE",
    "🎨 IMAGE STUDIO",
    "📐 DESIGN STUDIO",
    "📁 PROJECTS",
    "📚 DOCUMENTS"
])


# ============================================================
# CHAT
# ============================================================

with tabs[0]:

    st.subheader("Conversation with Vinci")

    for message in load_messages(st.session_state.cid):

        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    uploaded = st.file_uploader(
        "Attach a document or image",
        type=[
            "pdf", "docx", "txt", "md",
            "csv", "json", "py",
            "png", "jpg", "jpeg", "webp"
        ],
        key="chat_upload"
    )

    if uploaded:
        suffix = Path(uploaded.name).suffix.lower()

        if suffix in [".png", ".jpg", ".jpeg", ".webp"]:
            st.image(uploaded, width=220)
        else:
            try:
                st.session_state.document_context = (
                    extract_document(uploaded)[:40000]
                )
                st.success("Document extracted successfully.")
            except Exception as error:
                st.error(str(error))

    prompt = st.chat_input("Ask Vinci anything...")

    if prompt:

        save_message(st.session_state.cid, "user", prompt)

        image_data = None
        image_mime = "image/jpeg"

        if uploaded and Path(uploaded.name).suffix.lower() in [
            ".png", ".jpg", ".jpeg", ".webp"
        ]:
            image_data = uploaded.getvalue()
            image_mime = uploaded.type or image_mime

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):

            with st.spinner("Vinci is thinking..."):

                try:
                    answer = ask_vinci(
                        st.session_state.cid,
                        prompt,
                        model,
                        st.session_state.document_context,
                        st.session_state.research_context,
                        image_data,
                        image_mime
                    )

                    st.markdown(answer)

                    save_message(
                        st.session_state.cid,
                        "assistant",
                        answer
                    )

                except Exception as error:
                    st.error(f"Vinci error: {error}")

        st.rerun()


# ============================================================
# RESEARCH
# ============================================================

with tabs[1]:

    st.subheader("Engineering Research")

    query = st.text_input(
        "What should Vinci research?"
    )

    limit = st.slider("Number of sources", 3, 10, 6)

    if st.button("Search the web"):

        if query.strip():

            try:
                with st.spinner("Searching..."):
                    results = research_web(query, limit)

                formatted = []

                for i, item in enumerate(results, 1):

                    formatted.append(
                        f"[S{i}] {item['title']}\n"
                        f"{item['url']}\n"
                        f"{item['body']}"
                    )

                    with st.container(border=True):
                        st.markdown(f"**[S{i}] {item['title']}**")
                        st.write(item["body"])

                        if item["url"]:
                            st.markdown(
                                f"[Open source]({item['url']})"
                            )

                st.session_state.research_context = "\n\n".join(
                    formatted
                )

            except Exception as error:
                st.error(str(error))

        else:
            st.warning("Enter a research question.")

    if st.session_state.research_context:

        if st.button("Analyze research with Vinci"):

            
            question = (
                "Analyze the current research results. "
                "Compare the evidence, explain the findings, "
                "identify limitations, and cite sources using "
                "their S numbers."
            )

            save_message(
                st.session_state.cid,
                "user",
                question
            )

            with st.spinner("Vinci is analyzing the research..."):
                try:
                    answer = ask_vinci(
                        st.session_state.cid,
                        question,
                        model,
                        research=st.session_state.research_context
                    )

                    save_message(
                        st.session_state.cid,
                        "assistant",
                        answer
                    )

                    st.markdown(answer)

                except Exception as error:
                    st.error(f"Research analysis error: {error}")


# ============================================================
# VOICE — PUSH TO TALK
# ============================================================

with tabs[2]:

    st.subheader("Vinci Voice")

    st.info(
        "Push-to-talk mode: record a message, transcribe it, "
        "and receive a response. This is not continuous "
        "real-time voice streaming."
    )

    audio = st.audio_input("Record your message")

    if audio and st.button("Send voice message"):

        try:
            with st.spinner("Transcribing audio..."):
                transcript = transcribe_audio(audio)

            st.markdown("**Your transcription:**")
            st.write(transcript)

            if transcript.strip():

                save_message(
                    st.session_state.cid,
                    "user",
                    transcript
                )

                with st.spinner("Vinci is responding..."):

                    answer = ask_vinci(
                        st.session_state.cid,
                        transcript,
                        model
                    )

                save_message(
                    st.session_state.cid,
                    "assistant",
                    answer
                )

                st.markdown(answer)
                st.session_state.voice_answer = answer

        except Exception as error:
            st.error(f"Voice error: {error}")

    if st.session_state.get("voice_answer"):

        if st.button("Read answer aloud"):

            try:
                with st.spinner("Preparing audio..."):
                    audio_data = make_speech(
                        st.session_state.voice_answer
                    )

                st.audio(audio_data, format="audio/mp3")

            except Exception as error:
                st.error(f"Speech error: {error}")


# ============================================================
# IMAGE STUDIO — FREE IMAGE SERVICE
# ============================================================

with tabs[3]:

    st.subheader("Vinci Image Studio")

    st.info(
        "Uses an external image-generation service. "
        "No paid Gemini image-generation API is activated."
    )

    image_prompt = st.text_area(
        "Describe the image you want",
        height=120
    )

    aspect = st.selectbox(
        "Image format",
        ["Square", "Portrait", "Landscape"]
    )

    dimensions = {
        "Square": (1024, 1024),
        "Portrait": (768, 1024),
        "Landscape": (1024, 768)
    }

    if st.button("Generate image", type="primary"):

        if not image_prompt.strip():
            st.warning("Please enter an image description.")

        else:
            width, height = dimensions[aspect]

            try:
                with st.spinner("Generating image..."):
                    result = generate_free_image(
                        image_prompt,
                        width,
                        height
                    )

                # Validate the returned image before displaying it.
                image = Image.open(io.BytesIO(result))
                image.verify()

                st.session_state.last_image = result
                st.success("Image generated successfully.")

            except Exception as error:
                st.error(f"Image generation failed: {error}")

    if st.session_state.last_image:

        st.image(
            st.session_state.last_image,
            use_container_width=True
        )

        st.download_button(
            "Download image",
            data=st.session_state.last_image,
            file_name="vinci_image.png",
            mime="image/png"
        )


# ============================================================
# DESIGN STUDIO
# ============================================================

with tabs[4]:

    st.subheader("Engineering Design Studio")

    st.warning(
        "These are preliminary geometry and export tools. "
        "They do not replace professional CAD or circuit simulation."
    )

    design = st.radio(
        "Choose a workflow",
        [
            "3D Component",
            "2D Dimensional Drawing",
            "Circuit Design Brief"
        ],
        horizontal=True
    )

    if design == "3D Component":

        c1, c2, c3 = st.columns(3)

        length = c1.number_input(
            "Length (mm)", min_value=1.0, value=100.0
        )

        width = c2.number_input(
            "Width (mm)", min_value=1.0, value=60.0
        )

        height = c3.number_input(
            "Height (mm)", min_value=1.0, value=25.0
        )

        if go is not None:

            mesh = trimesh.creation.box(
                extents=(length, width, height)
            ) if trimesh is not None else None

            if mesh is not None:

                vertices = mesh.vertices
                faces = mesh.faces

                fig = go.Figure(
                    data=[
                        go.Mesh3d(
                            x=vertices[:, 0],
                            y=vertices[:, 1],
                            z=vertices[:, 2],
                            i=faces[:, 0],
                            j=faces[:, 1],
                            k=faces[:, 2],
                            color="#37cce8",
                            opacity=0.9
                        )
                    ]
                )

                fig.update_layout(
                    height=420,
                    scene=dict(aspectmode="data")
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True
                )

        if st.button("Prepare STL export"):

            try:
                stl_data = make_stl(
                    length,
                    width,
                    height
                )

                st.download_button(
                    "Download STL",
                    data=stl_data,
                    file_name="vinci_component.stl",
                    mime="model/stl"
                )

            except Exception as error:
                st.error(f"STL export error: {error}")

    elif design == "2D Dimensional Drawing":

        length = st.number_input(
            "Length (mm)", min_value=1.0, value=120.0
        )

        width = st.number_input(
            "Width (mm)", min_value=1.0, value=80.0
        )

        st.metric(
            "Surface area",
            f"{length * width:,.2f} mm²"
        )

        if st.button("Prepare DXF export"):

            try:
                drawing = make_dxf(length, width)

                st.download_button(
                    "Download DXF",
                    data=drawing,
                    file_name="vinci_drawing.dxf",
                    mime="application/dxf"
                )

            except Exception as error:
                st.error(f"DXF export error: {error}")

    else:

        st.subheader("Circuit Design Documentation")

        circuit_name = st.text_input("Circuit name")
        purpose = st.text_area("Circuit purpose")
        components = st.text_area("Components and ratings")
        constraints = st.text_area("Design constraints")

        if st.button("Prepare circuit design brief"):

            brief = f"""# {circuit_name}

## Purpose
{purpose}

## Components
{components}

## Design constraints
{constraints}

## Validation status
Conceptual design documentation only.
Not a validated circuit or simulation.
"""

            st.download_button(
                "Download design brief",
                data=brief,
                file_name="vinci_circuit_design.md",
                mime="text/markdown"
            )


# ============================================================
# PROJECTS AND REMINDERS
# ============================================================

with tabs[5]:

    st.subheader("JTEG Project Manager")

    with st.form("project_form"):

        project_name = st.text_input("Project name")
        description = st.text_area("Project description")

        submitted = st.form_submit_button("Save project")

    if submitted:

        if project_name.strip():

            with database() as conn:
                conn.execute(
                    """INSERT INTO projects
                    (name, description, status, created)
                    VALUES (?, ?, ?, ?)""",
                    (
                        project_name,
                        description,
                        "Planning",
                        timestamp()
                    )
                )

            st.success("Project saved.")
            st.rerun()

        else:
            st.warning("Enter a project name.")

    with database() as conn:
        projects = conn.execute(
            "SELECT * FROM projects ORDER BY id DESC"
        ).fetchall()

    for project in projects:

        with st.container(border=True):

            st.markdown(f"**{project['name']}**")
            st.write(project["description"])

            statuses = [
                "Planning",
                "In progress",
                "On hold",
                "Completed"
            ]

            current_status = (
                project["status"]
                if project["status"] in statuses
                else "Planning"
            )

            status = st.selectbox(
                "Project status",
                statuses,
                index=statuses.index(current_status),
                key=f"status_{project['id']}"
            )

            if status != project["status"]:

                with database() as conn:
                    conn.execute(
                        "UPDATE projects SET status=? WHERE id=?",
                        (status, project["id"])
                    )

                st.rerun()

            if st.button(
                "Delete project",
                key=f"delete_project_{project['id']}"
            ):

                with database() as conn:
                    conn.execute(
                        "DELETE FROM projects WHERE id=?",
                        (project["id"],)
                    )

                st.rerun()

    st.divider()
    st.subheader("Reminders")

    with st.form("reminder_form"):

        reminder_title = st.text_input("Reminder title")
        reminder_due = st.date_input("Due date")
        reminder_notes = st.text_area("Notes")

        submitted = st.form_submit_button("Save reminder")

    if submitted:

        if reminder_title.strip():

            with database() as conn:
                conn.execute(
                    """INSERT INTO reminders
                    (title, due, notes, completed)
                    VALUES (?, ?, ?, 0)""",
                    (
                        reminder_title,
                        reminder_due.isoformat(),
                        reminder_notes
                    )
                )

            st.success("Reminder saved.")
            st.rerun()

        else:
            st.warning("Enter a reminder title.")

    with database() as conn:
        reminders = conn.execute(
            "SELECT * FROM reminders ORDER BY due"
        ).fetchall()

    for reminder in reminders:

        with st.container(border=True):

            st.markdown(f"**{reminder['title']}**")
            st.caption(f"Due: {reminder['due']}")
            st.write(reminder["notes"])

            completed = st.checkbox(
                "Completed",
                value=bool(reminder["completed"]),
                key=f"completed_{reminder['id']}"
            )

            if completed != bool(reminder["completed"]):

                with database() as conn:
                    conn.execute(
                        "UPDATE reminders SET completed=? WHERE id=?",
                        (int(completed), reminder["id"])
                    )

                st.rerun()

            if st.button(
                "Delete reminder",
                key=f"delete_reminder_{reminder['id']}"
            ):

                with database() as conn:
                    conn.execute(
                        "DELETE FROM reminders WHERE id=?",
                        (reminder["id"],)
                    )

                st.rerun()


# ============================================================
# DOCUMENT LIBRARY
# ============================================================

with tabs[6]:

    st.subheader("Vinci Document Library")

    document = st.file_uploader(
        "Upload a document",
        type=["pdf", "docx", "txt", "md", "csv"]
    )

    if document and st.button("Extract and save document"):

        try:
            content = extract_document(document)

            if not content.strip():

                st.warning(
                    "No selectable text was found. "
                    "Scanned documents require OCR."
                )

            else:

                with database() as conn:
                    conn.execute(
                        """INSERT INTO documents
                        (filename, content, created)
                        VALUES (?, ?, ?)""",
                        (
                            document.name,
                            content,
                            timestamp()
                        )
                    )

                st.session_state.document_context = content[:40000]
                st.success("Document extracted and saved.")

        except Exception as error:
            st.error(f"Document extraction error: {error}")

    with database() as conn:
        documents = conn.execute(
            "SELECT * FROM documents ORDER BY id DESC"
        ).fetchall()

    for doc in documents:

        with st.expander(doc["filename"]):

            st.text_area(
                "Extracted content",
                doc["content"][:12000],
                height=200,
                key=f"document_{doc['id']}"
            )

            if st.button(
                "Use this document in chat",
                key=f"use_document_{doc['id']}"
            ):

                st.session_state.document_context = (
                    doc["content"][:40000]
                )

                st.success("Document context loaded.")

            if st.button(
                "Delete document",
                key=f"delete_document_{doc['id']}"
            ):

                with database() as conn:
                    conn.execute(
                        "DELETE FROM documents WHERE id=?",
                        (doc["id"],)
                    )

                st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.markdown("""
<div style="text-align:center;color:#9bb5c7;padding:15px">
    <b>VINCI AI</b><br>
    JTEG INTELLIGENCE PLATFORM<br>
    Engineering the systems that power modern civilization.
</div>
""", unsafe_allow_html=True)
                        
