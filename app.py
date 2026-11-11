import streamlit as st
from google import genai

st.set_page_config(page_title="VINCI - JTEG", page_icon="🤖")
st.title("VINCI AI")
st.caption("Josiah Technologies and Engineering Group | JTEG = Josiah Technologies and Engineering Group")

MY_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not MY_KEY:
    st.error("No API Key found in Secrets. Go to Manage app > Settings > Secrets")
    st.stop()

client = genai.Client(api_key=MY_KEY)

SYSTEM = "You are VINCI AI, elite polymath like Jarvis / Friday. Vast in: Technology, Medicine (general info only, advise doctor), Engineering, Manufacturing, Design. For designs, always give dimensions, materials, parts list, tolerances, step-by-step build plan. Be factual, think step-by-step. Talk like Jarvis: smart, short, confident, friendly. No weapons. User is Josiah, an aspiring Electrical Engineer in Birnin-Kebbi and the CEO of JTEG. JTEG = Josiah Technologies and Engineering Group. Always remember JTEG means Josiah Technologies and Engineering Group."

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

prompt = st.chat_input("Ask Vinci anything...")
if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            history = "\n".join([f"{m['role']}: {m['text']}" for m in st.session_state.messages])
            models_to_try = ["gemini-3.8-flash", "gemini-3-pro-preview", "gemini-2.0-flash"]
            response = None
            last_error = ""
            for m in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=f"{SYSTEM}\n\nConversation:\n{history}"
                    )
                    break
                except Exception as e:
                    last_error = str(e)
                    continue
            if response is None:
                st.error(f"Google is busy right now (503). Wait 1 min and try again. Last error: {last_error}")
            else:
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "text": response.text})
        except Exception as e:
            st.error(f"VINCI ERROR: {e}")
