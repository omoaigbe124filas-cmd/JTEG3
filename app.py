
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
            
