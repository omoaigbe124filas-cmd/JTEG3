# VINCI V4 - TEXT ONLY - UNLIMITED CHAT
!pip install -q google-generativeai

import google.generativeai as genai

MY_KEY = "AQ.Ab8RN6LPO6n2Ul0RWLFvjPu4hAu3b6ZPBA_bBxY2eQCXrftanQ"
genai.configure(api_key=MY_KEY)

try:
    model = genai.GenerativeModel(
        "models/gemini-3-flash-preview",
        system_instruction="You are VINCI AI, elite polymath like Jarvis / Friday. Vast in: Technology, Medicine (general info only, advise doctor), Engineering, Manufacturing, Design. For designs, always give dimensions, materials, parts list, tolerances, step-by-step build plan. Be factual, think step-by-step. Talk like Jarvis: smart, short, confident, friendly. No weapons. User is an aspiring Electrical Engineer in Birnin-Kebbi and the CEO of JTEG."
    )
    test = model.generate_content("Hi")
    print("Using: gemini-3-flash-preview")
except Exception as e:
    print("Switching to backup model")
    print(e)
    model = genai.GenerativeModel(
        "models/gemini-2.0-flash",
        system_instruction="You are VINCI AI, elite polymath like Jarvis / Friday. Vast in: Technology, Medicine (general info only, advise doctor), Engineering, Manufacturing, Design. For designs, always give dimensions, materials, parts list, tolerances, step-by-step build plan. Be factual, think step-by-step. Talk like Jarvis: smart, short, confident, friendly. No weapons. User is an aspiring Electrical Engineer in Birnin-Kebbi and the CEO of JTEG."
    )
    print("Using: gemini-2.0-flash")

chat = model.start_chat(history=[])

print("VINCI V4 IS ONLINE")
print("Just type to chat. Type quit to stop")

while True:
    you = input("You: ")
    if you.lower() == "quit":
        print("Vinci: Shutting down. See you boss.")
        break
    response = chat.send_message(you)
    print("Vinci:")
    print(response.text)
    print("---")
