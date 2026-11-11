import streamlit as st
from google import genai

st.set_page_config(page_title="VINCI - JTEG", page_icon="🤖")
st.title("VINCI AI")
st.caption("Josiah Technologies and Engineering Group | JTEG = Josiah Technologies and Engineering Group")

MY_KEY = st.secrets.get("GEMINI_API_KEY", "")
if not MY_KEY:
    st.error("No API Key in Secrets")
    st.stop()

client = genai.Client(api_key=MY_KEY)

if "messages" not in st.session_state:
    st.session_state.messages = []

if st.button("Clear chat"):
    st.session_state.messages = []
    st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

prompt = st.chat_input("Ask Vinci anything...")
if prompt:
    st.session_state.messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("VINCI is thinking..."):
            try:
                response = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=f"You are VINCI AI for JTEG = Josiah Technologies and Engineering Group. User is Josiah, aspiring Electrical Engineer in Birnin-Kebbi, CEO of JTEG. Be like Jarvis: smart, short, confident, friendly. User says: {prompt}"
                )
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "text": response.text})
            except Exception as e:
                st.error(f"Google busy, wait 1 min and try again: {e}")
