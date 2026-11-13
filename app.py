
import streamlit as st
import sqlite3
import os
import io
import json
import re
import asyncio
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

import httpx
import plotly.graph_objects as go
import trimesh

from google import genai
from google.genai import types
from pypdf import PdfReader
from docx import Document
from PIL import Image

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

try:
    import edge_tts
except ImportError:
    edge_tts = None

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
    layout="wide",
    initial_sidebar_state="expanded"
)

GEMINI_MODEL = "gemini-3.5-flash"

SYSTEM_PROMPT = """
You are Vinci AI, the engineering intelligence assistant of
Josiah Technologies and Engineering Group (JTEG).

Your platform name is JTEG Intelligence Platform.

You assist with:
- Engineering education and research.
- Electrical and electronic engineering concepts.
- Mechanical engineering concepts.
- Mathematics and physics.
- Software and programming.
- Engineering calculations.
- Product development and technical documentation.
- CAD and 3D design workflows.
- Image and document analysis.

Be accurate, clear and professional.

Show equations and units when useful.
Explain assumptions.
Distinguish estimated values from verified values.
Never invent research citations or claim a simulation was performed
when no simulation actually occurred.

For hazardous engineering topics, provide educational,
safety-focused explanations rather than dangerous hands-on
construction or live-testing instructions.
Recommend qualified professional supervision.
"""

# ============================================================
# VISUAL DESIGN
# ============================================================

st.markdown("""
<style>

@import url(
'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap'
);

:root {
    --vinci-cyan: #35d8ef;
    --vinci-blue: #2475d8;
    --vinci-bg: #0b1420;
}

.stApp {
    background:
        radial-gradient(
            circle at 15% 5%,
            rgba(20,105,145,.19),
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
    background: #0a1421;
    border-right: 1px solid rgba(80,190,220,.2);
}

h1, h2, h3 {
    font-family: 'Space Grotesk', sans-serif;
}

.stButton button {
    border-radius: 12px;
    border: 1px solid rgba(53,216,239,.5);
    background: linear-gradient(
        110deg,
        #116b99,
        #2856a9
    );
    color: white;
    font-weight: 600;
    min-height: 42px;
}

.stButton button:hover {
    border-color: #55efff;
    color: white;
}

.stDownloadButton button {
    border-radius: 10px;
}

[data-testid="stChatMessage"] {
    border-radius: 16px;
    border: 1px solid rgba(100,200,240,.12);
    background: rgba(255,255,255,.035);
    padding: 12px;
}

.hero {
    padding: 24px;
    border: 1px solid rgba(70,200,230,.3);
    border-radius: 20px;
    background: linear-gradient(
        120deg,
        rgba(14,107,143,.25),
        rgba(29,56,105,.22)
    );
}

.hero-label {
    color: #5ce8fa;
    letter-spacing: 2px;
    font-size: 11px;
    font-weight: 800;
}

.muted {
    color: #9bb4c9;
}

</style>
""", unsafe_allow_html=True)

# ============================================================
# CONFIGURATION
# ============================================================

def get_secret(name):
    try:
        return st.secrets.get(
            name,
            os.getenv(name, "")
        )
    except Exception:
        return os.getenv(name, "")

GEMINI_KEY = get_secret("GEMINI_API_KEY")

@st.cache_resource
def get_gemini_client():
    if not GEMINI_KEY:
        return None

    return genai.Client(api_key=GEMINI_KEY)

def gemini_request(contents, model=GEMINI_MODEL):
    client = get_gemini_client()

    if client is None:
        raise RuntimeError(
            "Gemini API key missing. Configure GEMINI_API_KEY "
            "in Streamlit Secrets."
        )

    return client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.5
        )
    )

# ============================================================
# DATABASE
# ============================================================

DATA_DIR = Path("vinci_data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "vinci.sqlite3"

def database():
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=30
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def now():
    return datetime.now(timezone.utc).isoformat()

def initialize_database():

    with database() as conn:

        conn.execute("PRAGMA journal_mode=WAL")

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created TEXT NOT NULL,
            FOREIGN KEY(conversation_id)
            REFERENCES conversations(id)
            ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS projects(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'Planning',
            created TEXT
        );

        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
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

initialize_database()

# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def create_conversation():

    with database() as conn:

        cursor = conn.execute(
            "INSERT INTO conversations(title,created) VALUES(?,?)",
            ("New conversation", now())
        )

        return cursor.lastrowid

def save_message(cid, role, content):

    with database() as conn:

        conn.execute(
            """
            INSERT INTO messages(
                conversation_id, role, content, created
            )
            VALUES(?,?,?,?)
            """,
            (cid, role, content, now())
        )

        if role == "user":

            count = conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE conversation_id=?
                """,
                (cid,)
            ).fetchone()[0]

            if count == 1:

                title = content.replace("\n", " ")[:55]

                conn.execute(
                    """
                    UPDATE conversations
                    SET title=?
                    WHERE id=?
                    """,
                    (title, cid)
                )

def get_messages(cid):

    with database() as conn:

        return conn.execute(
            """
            SELECT role,content FROM messages
            WHERE conversation_id=?
            ORDER BY id
            """,
            (cid,)
        ).fetchall()

def get_conversations():

    with database() as conn:

        return conn.execute(
            """
            SELECT * FROM conversations
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()

def delete_conversation(cid):

    with database() as conn:

        conn.execute(
            "DELETE FROM conversations WHERE id=?",
            (cid,)
        )

# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "cid": None,
    "page": "Chat",
    "research_results": [],
    "document_context": "",
    "design_result": None,
    "design_image": None,
    "last_image": None,
    "voice_answer": "",
}

for key, value in DEFAULTS.items():

    if key not in st.session_state:
        st.session_state[key] = value

if st.session_state.cid is None:
    st.session_state.cid = create_conversation()

# ============================================================
# GEMINI CONVERSATION ENGINE
# ============================================================

def build_history(cid, additional_document=""):

    rows = get_messages(cid)

    contents = []

    for row in rows[-30:]:

        role = (
            "user"
            if row["role"] == "user"
            else "model"
        )

        contents.append(
            types.Content(
                role=role,
                parts=[
                    types.Part.from_text(
                        text=row["content"]
                    )
                ]
            )
        )

    if additional_document and contents:

        last = contents[-1]

        parts = list(last.parts)

        parts.append(
            types.Part.from_text(
                text=(
                    "\n\nDOCUMENT CONTEXT:\n"
                    + additional_document[:30000]
                )
            )
        )

        contents[-1] = types.Content(
            role="user",
            parts=parts
        )

    return contents

def ask_vinci(
    cid,
    prompt,
    image_bytes=None,
    image_mime="image/jpeg",
    document=""
):

    contents = build_history(cid)

    # A current prompt is added once. Do not repeat the
    # last saved user message in the history.
    if not contents or contents[-1].role != "user":

        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt)
                ]
            )
        )

    elif contents:

        # The latest user message has already been saved.
        last = contents[-1]
        parts = list(last.parts)

        if document:

            parts.append(
                types.Part.from_text(
                    text="\nDOCUMENT CONTEXT:\n"
                    + document[:30000]
                )
            )

        if image_bytes:

            parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=image_mime
                )
            )

        contents[-1] = types.Content(
            role="user",
            parts=parts
        )

    response = gemini_request(contents)

    return response.text or "Vinci could not generate a response."

def analyze_image_with_gemini(image_bytes, mime_type, prompt):

    contents = [
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type
        )
    ]

    response = gemini_request(contents)

    return response.text or ""

# ============================================================
# DOCUMENT EXTRACTION
# ============================================================

def extract_document(upload):

    data = upload.getvalue()
    name = upload.name.lower()

    if name.endswith(".pdf"):

        reader = PdfReader(io.BytesIO(data))

        pages = []

        for number, page in enumerate(reader.pages, 1):

            text = page.extract_text() or ""

            if text.strip():

                pages.append(
                    f"PAGE {number}\n{text}"
                )

        return "\n\n".join(pages)

    if name.endswith(".docx"):

        document = Document(io.BytesIO(data))

        paragraphs = [
            paragraph.text
            for paragraph in document.paragraphs
        ]

        for table in document.tables:

            for row in table.rows:

                paragraphs.append(
                    " | ".join(
                        cell.text
                        for cell in row.cells
                    )
                )

        return "\n".join(paragraphs)

    if name.endswith(
        (".txt", ".md", ".csv", ".json", ".py")
    ):

        return data.decode(
            "utf-8",
            errors="replace"
        )

    raise ValueError("Unsupported document format.")

# ============================================================
# WEB RESEARCH
# ============================================================

def research_web(query, limit=6):

    if DDGS is None:

        raise RuntimeError(
            "Research library missing. Install ddgs."
        )

    with DDGS() as search:

        results = search.text(
            query,
            max_results=limit
        )

    return [
        {
            "title": item.get("title", ""),
            "url": item.get("href", ""),
            "body": item.get("body", "")
        }
        for item in results
    ]

# ============================================================
# FREE IMAGE GENERATION
# ============================================================

def generate_free_image(prompt, width=1024, height=1024):

    encoded = urllib.parse.quote(
        prompt,
        safe=""
    )

    url = (
        "https://image.pollinations.ai/prompt/"
        + encoded
        + f"?width={width}&height={height}"
        + "&model=flux&nologo=true&safe=true"
    )

    with httpx.Client(
        timeout=180,
        follow_redirects=True
    ) as client:

        response = client.get(url)
        response.raise_for_status()

    image = Image.open(
        io.BytesIO(response.content)
    )

    image.verify()

    return response.content

# ============================================================
# VOICE
# ============================================================

def transcribe_audio(audio):

    response = gemini_request([
        types.Part.from_text(
            text=(
                "Transcribe the audio accurately. "
                "Return only the transcription."
            )
        ),
        types.Part.from_bytes(
            data=audio.getvalue(),
            mime_type=audio.type or "audio/wav"
        )
    ])

    return response.text or ""

def make_speech(text):

    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed.")

    async def generate():

        communicator = edge_tts.Communicate(
            text,
            "en-NG-AbeoNeural"
        )

        output = bytearray()

        async for chunk in communicator.stream():

            if chunk["type"] == "audio":
                output.extend(chunk["data"])

        return bytes(output)

    try:
        return asyncio.run(generate())

    except RuntimeError:

        loop = asyncio.new_event_loop()

        try:
            return loop.run_until_complete(generate())

        finally:
            loop.close()

# ============================================================
# DESIGN STUDIO — AI IMAGE ANALYSIS
# ============================================================

DESIGN_PROMPT = """
Analyze the uploaded product or engineering object.

Create an approximate editable component breakdown.

Return ONLY valid JSON using this structure:

{
  "name": "Object name",
  "dimensions_mm": [300, 200, 250],
  "confidence": "approximate",
  "components": [
    {
      "name": "Main housing",
      "primitive": "box",
      "dimensions_mm": [300, 200, 250],
      "position_mm": [0, 0, 0],
      "color": "#55aadd",
      "description": "Outer body"
    },
    {
      "name": "Internal cylinder",
      "primitive": "cylinder",
      "dimensions_mm": [30, 30, 100],
      "position_mm": [0, 0, 0],
      "color": "#aaaaaa",
      "description": "Approximate internal component"
    }
  ]
}

Rules:
- Use box, cylinder or sphere primitives.
- All dimensions must be positive numbers in millimetres.
- Position uses x, y, z coordinates.
- Include only visible or reasonably inferable components.
- Clearly describe inferred or hidden components as estimates.
- Do not invent exact measurements from a photograph.
- Use between 2 and 12 components.
- Use simple, editable geometry.
"""

def parse_design_json(text):

    text = text.strip()

    text = re.sub(
        r"^```(?:json)?",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"```$",
        "",
        text
    ).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start < 0 or end < 0:
        raise ValueError("AI did not return valid JSON.")

    return json.loads(text[start:end + 1])

def validate_design(data):

    components = data.get("components", [])

    if not isinstance(components, list):
        raise ValueError("Invalid component list.")

    clean = []

    for item in components[:12]:

        primitive = item.get("primitive", "box")

        if primitive not in ["box", "cylinder", "sphere"]:
            primitive = "box"

        dimensions = item.get(
            "dimensions_mm",
            [50, 50, 50]
        )

        position = item.get(
            "position_mm",
            [0, 0, 0]
        )

        if len(dimensions) != 3 or len(position) != 3:
            continue

        dimensions = [
            max(1.0, min(float(v), 5000.0))
            for v in dimensions
        ]

        position = [
            max(-5000.0, min(float(v), 5000.0))
            for v in position
        ]

        clean.append({
            "name": str(item.get("name", "Component"))[:80],
            "primitive": primitive,
            "dimensions_mm": dimensions,
            "position_mm": position,
            "color": str(item.get("color", "#55aadd")),
            "description": str(item.get("description", ""))[:250]
        })

    if not clean:
        raise ValueError("No usable components were returned.")

    return {
        "name": str(data.get("name", "Engineering object")),
        "dimensions_mm": data.get(
            "dimensions_mm",
            [100, 100, 100]
        ),
        "confidence": str(
            data.get("confidence", "approximate")
        ),
        "components": clean
    }

def analyze_design_photo(upload):

    image_bytes = upload.getvalue()
    mime = upload.type or "image/jpeg"

    result = analyze_image_with_gemini(
        image_bytes,
        mime,
        DESIGN_PROMPT
    )

    design = parse_design_json(result)

    return validate_design(design)

# ============================================================
# 3D GEOMETRY
# ============================================================

def component_mesh(component, explosion=0.0, index=0):

    dimensions = component["dimensions_mm"]

    if component["primitive"] == "cylinder":

        mesh = trimesh.creation.cylinder(
            radius=dimensions[0] / 2,
            height=dimensions[2],
            sections=24
        )

    elif component["primitive"] == "sphere":

        mesh = trimesh.creation.icosphere(
            subdivisions=2,
            radius=dimensions[0] / 2
        )

    else:

        mesh = trimesh.creation.box(
            extents=dimensions
        )

    x, y, z = component["position_mm"]

    # Separate parts along the X axis in exploded mode.
    shift = index * explosion

    mesh.apply_translation(
        [
            x + shift,
            y,
            z
        ]
    )

    return mesh

def render_3d_design(design, explosion=0.0):

    figure = go.Figure()

    for index, component in enumerate(
        design["components"]
    ):

        mesh = component_mesh(
            component,
            explosion,
            index
        )

        vertices = mesh.vertices
        faces = mesh.faces

        figure.add_trace(
            go.Mesh3d(
                x=vertices[:, 0],
                y=vertices[:, 1],
                z=vertices[:, 2],
                i=faces[:, 0],
                j=faces[:, 1],
                k=faces[:, 2],
                color=component["color"],
                opacity=0.9,
                name=component["name"],
                hovertext=component["name"],
                hoverinfo="text",
                showlegend=True
            )
        )

    figure.update_layout(
        height=520,
        margin=dict(l=0, r=0, t=20, b=0),
        scene=dict(
            aspectmode="data",
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Z (mm)"
        ),
        legend=dict(
            orientation="h",
            y=-0.15
        )
    )

    return figure

def render_2d_exploded(design, separation=1.0):

    figure = go.Figure()

    for index, component in enumerate(
        design["components"]
    ):

        x, y, z = component["position_mm"]
        dx, dy, dz = component["dimensions_mm"]

        shift = index * separation * max(dx, 25)

        left = x + shift
        right = left + dx

        bottom = y
        top = y + dy

        figure.add_shape(
            type="rect",
            x0=left,
            y0=bottom,
            x1=right,
            y1=top,
            line=dict(
                color=component["color"],
                width=2
            ),
            fillcolor=component["color"],
            opacity=0.45
        )

        figure.add_annotation(
            x=(left + right) / 2,
            y=top + 5,
            text=component["name"],
            showarrow=False,
            font=dict(size=10)
        )

    figure.update_layout(
        height=480,
        title="Approximate 2D exploded component layout",
        xaxis_title="X position (mm)",
        yaxis_title="Y position (mm)",
        showlegend=False
    )

    return figure

# ============================================================
# ENGINEERING EXPORTS
# ============================================================

def export_stl(design, explosion=0.0):

    meshes = []

    for index, component in enumerate(
        design["components"]
    ):

        mesh = component_mesh(
            component,
            explosion,
            index
        )

        meshes.append(mesh)

    combined = trimesh.util.concatenate(meshes)

    return combined.export(file_type="stl")

def export_dxf(design):

    if ezdxf is None:
        raise RuntimeError("ezdxf is not installed.")

    doc = ezdxf.new("R2010")
    model = doc.modelspace()

    for component in design["components"]:

        x, y, z = component["position_mm"]
        dx, dy, dz = component["dimensions_mm"]

        model.add_lwpolyline(
            [
                (x, y),
                (x + dx, y),
                (x + dx, y + dy),
                (x, y + dy),
                (x, y)
            ],
            close=True
        )

        model.add_text(
            component["name"],
            dxfattribs={
                "height": max(2, min(dx, dy) * 0.04),
                "insert": (x, y + dy + 3)
            }
        )

    output = io.StringIO()
    doc.write(output)

    return output.getvalue().encode("utf-8")

# ============================================================
# SIDEBAR — SLIDE-OUT WORKSPACE
# ============================================================

PAGES = [
    "Chat",
    "Research",
    "Projects",
    "Documents",
    "Image Studio",
    "Design Studio",
    "Voice",
    "Plugins",
    "Settings"
]

with st.sidebar:

    st.markdown("## 🤖 Vinci AI")
    st.caption("JTEG Intelligence Platform")

    if GEMINI_KEY:
        st.success("Gemini connected")
    else:
        st.error("Gemini API key missing")

    st.divider()

    if st.button("＋ New chat", use_container_width=True):

        st.session_state.cid = create_conversation()
        st.session_state.document_context = ""
        st.rerun()

    st.markdown("### Workspace")

    page = st.radio(
        "Navigation",
        PAGES,
        key="page",
        label_visibility="collapsed"
    )

    st.divider()

    st.markdown("### Conversation history")

    for item in get_conversations():

        if st.button(
            item["title"][:32],
            key=f"conversation_{item['id']}",
            use_container_width=True
        ):

            st.session_state.cid = item["id"]
            st.session_state.page = "Chat"
            st.rerun()

        if st.button(
            "Delete",
            key=f"delete_conversation_{item['id']}"
        ):

            delete_conversation(item["id"])

            if item["id"] == st.session_state.cid:
                st.session_state.cid = create_conversation()

            st.rerun()

# ============================================================
# HEADER
# ============================================================

st.markdown("""
<div class="hero">
    <div class="hero-label">
        JOSIAH TECHNOLOGIES AND ENGINEERING GROUP
    </div>
    <h1 style="color:white;margin:5px 0">
        Vinci AI
    </h1>
    <h3 style="color:#55dff5;margin:0">
        JTEG Intelligence Platform
    </h3>
    <p class="muted">
        Engineering knowledge. Research. Design. Intelligence.
    </p>
</div>
""", unsafe_allow_html=True)

st.write("")

# ============================================================
# CHAT WORKSPACE
# ============================================================

if page == "Chat":

    st.subheader("Chat")

    for message in get_messages(st.session_state.cid):

        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    attachment = st.file_uploader(
        "Attach an image or document",
        type=[
            "pdf", "docx", "txt", "md",
            "csv", "png", "jpg", "jpeg", "webp"
        ],
        key="chat_attachment"
    )

    image_bytes = None
    image_mime = "image/jpeg"

    if attachment:

        suffix = Path(attachment.name).suffix.lower()

        if suffix in [".png", ".jpg", ".jpeg", ".webp"]:

            image_bytes = attachment.getvalue()
            image_mime = attachment.type or image_mime

            st.image(
                image_bytes,
                width=220
            )

        else:

            try:

                st.session_state.document_context = (
                    extract_document(attachment)[:30000]
                )

                st.success("Document extracted.")

            except Exception as error:
                st.error(str(error))

    prompt = st.chat_input(
        "Message Vinci AI..."
    )

    if prompt:

        save_message(
            st.session_state.cid,
            "user",
            prompt
        )

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):

            with st.spinner("Vinci is thinking..."):

                try:

                    answer = ask_vinci(
                        st.session_state.cid,
                        prompt,
                        image_bytes,
                        image_mime,
                        st.session_state.document_context
                    )

                    st.markdown(answer)

                    save_message(
                        st.session_state.cid,
                        "assistant",
                        answer
                    )

                except Exception as error:

                    st.error(
                        f"Gemini error: {error}"
                    )

        st.rerun()

# ============================================================
# RESEARCH WORKSPACE
# ============================================================

elif page == "Research":

    st.subheader("Research")

    query = st.text_input(
        "What would you like Vinci to research?"
    )

    limit = st.slider(
        "Number of sources",
        3,
        10,
        6
    )

    if st.button("Search research sources"):

        if query.strip():

            try:

                with st.spinner("Searching..."):

                    results = research_web(
                        query,
                        limit
                    )

                st.session_state.research_results = results

            except Exception as error:
                st.error(str(error))

    results = st.session_state.research_results

    if results:

        research_text = []

        for index, item in enumerate(results, 1):

            research_text.append(
                f"[S{index}] {item['title']}\n"
                f"{item['url']}\n"
                f"{item['body']}"
            )

            with st.container(border=True):

                st.markdown(
                    f"**[S{index}] {item['title']}**"
                )

                st.write(item["body"])

                if item["url"]:
                    st.markdown(
                        f"[Open source]({item['url']})"
                    )

        if st.button("Use Vinci to analyze results"):

            prompt = (
                "Analyze these research results. "
                "Explain the findings, compare the evidence, "
                "identify limitations and cite the sources "
                "using their S numbers:\n\n"
                + "\n\n".join(research_text)
            )

            save_message(
                st.session_state.cid,
                "user",
                "Analyze the research results."
            )

            try:

                with st.spinner("Analyzing research..."):

                    answer = ask_vinci(
                        st.session_state.cid,
                        "Analyze the supplied research sources."
                    )

                # The sources are added as a separate user turn
                # to avoid losing them from the model context.
                response = gemini_request([
                    types.Part.from_text(
                        text=SYSTEM_PROMPT
                    ),
                    types.Part.from_text(
                        text=prompt
                    )
                ])

                answer = response.text or answer

                save_message(
                    st.session_state.cid,
                    "assistant",
                    answer
                )

                st.markdown(answer)

            except Exception as error:
                st.error(str(error))

# ============================================================
# PROJECTS
# ============================================================

elif page == "Projects":

    st.subheader("JTEG Project Manager")

    with st.form("project_form"):

        name = st.text_input("Project name")
        description = st.text_area("Project description")

        submitted = st.form_submit_button("Save project")

    if submitted:

        if name.strip():

            with database() as conn:

                conn.execute(
                    """
                    INSERT INTO projects(
                        name, description, status, created
                    )
                    VALUES(?,?,?,?)
                    """,
                    (
                        name,
                        description,
                        "Planning",
                        now()
                    )
                )

            st.success("Project saved.")
            st.rerun()

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

            status = st.selectbox(
                "Status",
                statuses,
                index=(
                    statuses.index(project["status"])
                    if project["status"] in statuses
                    else 0
                ),
                key=f"project_status_{project['id']}"
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
                key=f"project_delete_{project['id']}"
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

        title = st.text_input("Reminder title")
        due = st.date_input("Due date")
        notes = st.text_area("Notes")

        submitted = st.form_submit_button("Save reminder")

    if submitted and title.strip():

        with database() as conn:

            conn.execute(
                """
                INSERT INTO reminders(title,due,notes)
                VALUES(?,?,?)
                """,
                (
                    title,
                    due.isoformat(),
                    notes
                )
            )

        st.success("Reminder saved.")
        st.rerun()

    with database() as conn:

        reminders = conn.execute(
            "SELECT * FROM reminders ORDER BY due"
        ).fetchall()

    for reminder in reminders:

        with st.container(border=True):

            st.write(reminder["title"])
            st.caption(reminder["due"])
            st.write(reminder["notes"])

            done = st.checkbox(
                "Completed",
                value=bool(reminder["completed"]),
                key=f"reminder_{reminder['id']}"
            )

            if done != bool(reminder["completed"]):

                with database() as conn:

                    conn.execute(
                        "UPDATE reminders SET completed=? WHERE id=?",
                        (int(done), reminder["id"])
                    )

                st.rerun()

# ============================================================
# DOCUMENT LIBRARY
# ============================================================

elif page == "Documents":

    st.subheader("Document Library")

    upload = st.file_uploader(
        "Upload PDF, Word or text document",
        type=["pdf", "docx", "txt", "md", "csv"]
    )

    if upload and st.button("Extract and save"):

        try:

            content = extract_document(upload)

            if not content.strip():

                st.warning(
                    "No selectable text found. "
                    "Scanned documents require OCR."
                )

            else:

                with database() as conn:

                    conn.execute(
                        """
                        INSERT INTO documents(
                            filename,content,created
                        )
                        VALUES(?,?,?)
                        """,
                        (
                            upload.name,
                            content,
                            now()
                        )
                    )

                st.success("Document saved.")

        except Exception as error:
            st.error(str(error))

    with database() as conn:

        documents = conn.execute(
            "SELECT * FROM documents ORDER BY id DESC"
        ).fetchall()

    for document in documents:

        with st.expander(document["filename"]):

            st.text_area(
                "Extracted text",
                document["content"][:15000],
                height=200,
                key=f"document_view_{document['id']}"
            )

            if st.button(
                "Load into chat",
                key=f"document_load_{document['id']}"
            ):

                st.session_state.document_context = (
                    document["content"][:30000]
                )

                st.success(
                    "Document loaded. Open Chat to use it."
                )

            if st.button(
                "Delete document",
                key=f"document_delete_{document['id']}"
            ):

                with database() as conn:

                    conn.execute(
                        "DELETE FROM documents WHERE id=?",
                        (document["id"],)
                    )

                st.rerun()

# ============================================================
# IMAGE STUDIO
# ============================================================

elif page == "Image Studio":

    st.subheader("Vinci Image Studio")

    st.info(
        "Uses an external best-effort image service. "
        "No paid Gemini image generation is activated."
    )

    prompt = st.text_area(
        "Describe the image",
        height=120
    )

    aspect = st.selectbox(
        "Image format",
        ["Square", "Portrait", "Landscape"]
    )

    sizes = {
        "Square": (1024, 1024),
        "Portrait": (768, 1024),
        "Landscape": (1024, 768)
    }

    if st.button("Generate image"):

        if not prompt.strip():

            st.warning("Enter an image description.")

        else:

            width, height = sizes[aspect]

            try:

                with st.spinner("Generating..."):

                    image_data = generate_free_image(
                        prompt,
                        width,
                        height
                    )

                st.session_state.last_image = image_data

            except Exception as error:
                st.error(str(error))

    if st.session_state.last_image:

        st.image(
            st.session_state.last_image,
            use_container_width=True
        )

        st.download_button(
            "Download image",
            st.session_state.last_image,
            "vinci_image.png",
            "image/png"
        )

# ============================================================
# DESIGN STUDIO
# ============================================================

elif page == "Design Studio":

    st.subheader("Engineering Design Studio")

    workflow = st.radio(
        "Design workflow",
        ["3D Modeling", "2D Drawing"],
        horizontal=True
    )

    st.divider()

    # --------------------------------------------------------
    # MANUAL 3D DESIGN
    # --------------------------------------------------------

    if workflow == "3D Modeling":

        st.markdown("### Parametric 3D component")

        with st.form("3d_dimensions_form"):

            c1, c2, c3 = st.columns(3)

            length = c1.number_input(
                "Length (mm)",
                min_value=1.0,
                max_value=5000.0,
                value=300.0
            )

            width = c2.number_input(
                "Width (mm)",
                min_value=1.0,
                max_value=5000.0,
                value=200.0
            )

            height = c3.number_input(
                "Height (mm)",
                min_value=1.0,
                max_value=5000.0,
                value=900.0
            )

            create = st.form_submit_button(
                "Generate 3D model"
            )

        if create:

            st.session_state.design_result = {
                "name": "Custom component",
                "confidence": "User-defined dimensions",
                "components": [
                    {
                        "name": "Main housing",
                        "primitive": "box",
                        "dimensions_mm": [
                            length,
                            width,
                            height
                        ],
                        "position_mm": [0, 0, 0],
                        "color": "#38a9d8",
                        "description": "Main enclosure"
                    }
                ]
            }

        design = st.session_state.design_result

        if design:

            st.markdown("### 3D preview")

            separation = st.slider(
                "Exploded view separation",
                0.0,
                150.0,
                0.0,
                key="manual_explode"
            )

            figure = render_3d_design(
                design,
                separation
            )

            st.plotly_chart(
                figure,
                use_container_width=True,
                key="manual_3d_preview"
            )

            st.write("### Components")

            for item in design["components"]:
                st.write(
                    f"**{item['name']}** — "
                    f"{item['dimensions_mm']} mm"
                )

            if st.button("Prepare STL file"):

                try:

                    st.session_state.stl_file = export_stl(
                        design,
                        separation
                    )

                except Exception as error:
                    st.error(str(error))

            if st.session_state.get("stl_file"):

                st.download_button(
                    "Download STL",
                    st.session_state.stl_file,
                    "vinci_model.stl",
                    "model/stl"
                )

    # --------------------------------------------------------
    # 2D DESIGN
    # --------------------------------------------------------

    else:

        st.markdown("### 2D dimensional drawing")

        with st.form("2d_dimensions_form"):

            length = st.number_input(
                "Length (mm)",
                min_value=1.0,
                value=300.0
            )

            width = st.number_input(
                "Width (mm)",
                min_value=1.0,
                value=200.0
            )

            create = st.form_submit_button(
                "Generate drawing"
            )

        if create:

            st.session_state.design_result = {
                "name": "2D rectangular component",
                "confidence": "User-defined dimensions",
                "components": [
                    {
                        "name": "Main body",
                        "primitive": "box",
                        "dimensions_mm": [
                            length,
                            width,
                            20.0
                        ],
                        "position_mm": [0, 0, 0],
                        "color": "#42a9d9",
                        "description": "Main body"
                    }
                ]
            }

        design = st.session_state.design_result

        if design:

            separation = st.slider(
                "2D exploded separation",
                0.0,
                2.0,
                1.0
            )

            figure = render_2d_exploded(
                design,
                separation
            )

            st.plotly_chart(
                figure,
                use_container_width=True
            )

            if st.button("Prepare DXF file"):

                try:

                    st.session_state.dxf_file = export_dxf(
                        design
                    )

                except Exception as error:
                    st.error(str(error))

            if st.session_state.get("dxf_file"):

                st.download_button(
                    "Download DXF",
                    st.session_state.dxf_file,
                    "vinci_drawing.dxf",
                    "application/dxf"
                )

    # --------------------------------------------------------
    # PHOTO-TO-DESIGN WORKSPACE
    # --------------------------------------------------------

    st.divider()

    st.markdown("### Photo-to-Design")
    st.caption(
        "Upload a photograph of an object for AI-assisted "
        "component analysis and approximate design."
    )

    left, right = st.columns([1, 2])

    with left:

        design_photo = st.file_uploader(
            "Upload engineering photograph",
            type=["jpg", "jpeg", "png", "webp"],
            key="design_photo"
        )

        if design_photo:

            st.image(
                design_photo,
                use_container_width=True
            )

        analyze_button = st.button(
            "Analyze photograph",
            type="primary"
        )

    with right:

        st.markdown("**Analysis capabilities**")

        st.write(
            "- Identify visible components.\n"
            "- Estimate approximate dimensions.\n"
            "- Generate an editable component breakdown.\n"
            "- Produce an approximate 3D assembly.\n"
            "- Create a 2D exploded component diagram."
        )

    if analyze_button:

        if not design_photo:

            st.warning("Upload a photograph first.")

        else:

            try:

                with st.spinner(
                    "Vinci is analyzing the engineering object..."
                ):

                    result = analyze_design_photo(
                        design_photo
                    )

                st.session_state.design_result = result

                st.success("Component analysis completed.")

            except Exception as error:

                st.error(
                    f"Photo analysis failed: {error}"
                )

    design = st.session_state.design_result

    if design and design.get("components"):

        st.divider()

        st.markdown(
            f"### {design['name']}"
        )

        st.caption(
            "Dimensions and internal components are estimates "
            "unless independently measured."
        )

        for index, component in enumerate(
            design["components"],
            1
        ):

            with st.expander(
                f"{index}. {component['name']}"
            ):

                st.write(
                    "Type:",
                    component["primitive"]
                )

                st.write(
                    "Dimensions (mm):",
                    component["dimensions_mm"]
                )

                st.write(
                    "Position (mm):",
                    component["position_mm"]
                )

                st.write(
                    component["description"]
                )

        if workflow == "3D Modeling":

            st.markdown("### Interactive 3D assembly")

            explode = st.slider(
                "Explode components",
                0.0,
                200.0,
                0.0,
                key="photo_3d_explode"
            )

            figure = render_3d_design(
                design,
                explode
            )

            st.plotly_chart(
                figure,
                use_container_width=True,
                key="photo_3d_figure"
            )

            if st.button("Prepare photo-based STL"):

                try:

                    st.session_state.photo_stl = export_stl(
                        design,
                        explode
                    )

                except Exception as error:
                    st.error(str(error))

            if st.session_state.get("photo_stl"):

                st.download_button(
                    "Download 3D STL",
                    st.session_state.photo_stl,
                    "vinci_exploded_model.stl",
                    "model/stl"
                )

        else:

            st.markdown("### 2D exploded breakdown")

            separation = st.slider(
                "Component separation",
                0.0,
                2.0,
                1.0,
                key="photo_2d_explode"
            )

            figure = render_2d_exploded(
                design,
                separation
            )

            st.plotly_chart(
                figure,
                use_container_width=True
            )

            if st.button("Prepare photo-based DXF"):

                try:

                    st.session_state.photo_dxf = export_dxf(
                        design
                    )

                except Exception as error:
                    st.error(str(error))

            if st.session_state.get("photo_dxf"):

                st.download_button(
                    "Download 2D DXF",
                    st.session_state.photo_dxf,
                    "vinci_exploded_drawing.dxf",
                    "application/dxf"
                )

# ============================================================
# VOICE
# ============================================================

elif page == "Voice":

    st.subheader("Vinci Voice")

    st.info(
        "Push-to-talk voice input. This is not a continuous "
        "real-time voice connection."
    )

    audio = st.audio_input("Record a message")

    if audio and st.button("Transcribe and send"):

        try:

            transcript = transcribe_audio(audio)

            st.write("**Transcription:**")
            st.write(transcript)

            if transcript.strip():

                save_message(
                    st.session_state.cid,
                    "user",
                    transcript
                )

                answer = ask_vinci(
                    st.session_state.cid,
                    transcript
                )

                save_message(
                    st.session_state.cid,
                    "assistant",
                    answer
                )

                st.session_state.voice_answer = answer

                st.markdown(answer)

        except Exception as error:
            st.error(str(error))

    if st.session_state.voice_answer:

        if st.button("Read answer aloud"):

            try:

                audio_data = make_speech(
                    st.session_state.voice_answer
                )

                st.audio(
                    audio_data,
                    format="audio/mp3"
                )

            except Exception as error:
                st.error(str(error))

# ============================================================
# PLUGINS
# ============================================================

elif page == "Plugins":

    st.subheader("Vinci Extensions")

    st.info(
        "The plugin workspace is prepared for future integrations. "
        "No external plugin is connected automatically."
    )

    with st.container(border=True):

        st.markdown("**Gemini Intelligence Engine**")
        st.write("Primary AI provider: Google Gemini")

        st.markdown("**Research tools**")
        st.write("Web search integration")

        st.markdown("**Engineering tools**")
        st.write("Plotly, Trimesh and DXF export")

# ============================================================
# SETTINGS
# ============================================================

elif page == "Settings":

    st.subheader("Vinci AI Settings")

    st.write("**Platform:** JTEG Intelligence Platform")
    st.write("**AI provider:** Google Gemini")
    st.write("**Chat model:**", GEMINI_MODEL)

    st.write(
        "**Database:**",
        str(DB_PATH)
    )

    if GEMINI_KEY:
        st.success("Gemini API key is configured.")
    else:
        st.error("Gemini API key is not configured.")

    st.caption(
        "Keep your API key in Streamlit Secrets. "
        "Never publish it in your GitHub source code."
    )

# ============================================================
# FOOTER
# ============================================================

st.divider()

st.markdown("""
<div style="text-align:center;color:#91afc4;padding:16px">
    <b>VINCI AI</b><br>
    JTEG INTELLIGENCE PLATFORM<br>
    Made in Nigeria. Built for the World.
</div>
""", unsafe_allow_html=True)

    
