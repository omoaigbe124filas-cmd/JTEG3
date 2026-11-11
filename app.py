import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="VINCI - JTEG", page_icon="🤖")
st.title("VINCI AI")
st.caption("Josiah Technologies and Engineering Group | JTEG = Josiah Technologies and Engineering Group")

# Get key from secrets
try:
    MY_KEY = st.secrets["GEMINI_API_KEY"]
except:
    MY_KEY = st.text_input("Paste your Gemini API Key", type="password")
    if not MY_KEY:
        st.stop()

genai.configure(api_key=MY_KEY)
model = genai.GenerativeModel(
    "models/gemini-2.0-flash",
    system_instruction="You are VINCI AI, elite polymath like Jarvis / Friday. Vast in: Technology, Medicine (general info only, advise doctor), Engineering, Manufacturing, Design. For designs, always give dimensions, materials, parts list, tolerances, step-by-step build plan. Be factual, think step-by-step. Talk like Jarvis: smart, short, confident, friendly. No weapons. User is Josiah, an aspiring Electrical Engineer in Birnin-Kebbi and the CEO of JTEG. JTEG = Josiah Technologies and Engineering Group. Always remember JTEG means Josiah Technologies and Engineering Group."
)

if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])
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
        response = st.session_state.chat.send_message(prompt)
        st.markdown(response.text)
        st.session_state.messages.append({"role": "assistant", "text": response.text})
