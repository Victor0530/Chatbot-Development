import os
import streamlit as st
import requests
import uuid

# Base API URL
# Defaults to localhost for native runs; docker-compose.yml overrides this to
# http://backend:8000 so the frontend container can reach the backend by service name.
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Online Ticketing Chatbot Dashboard",
    page_icon="🎟️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for rich aesthetics (Glassmorphism, custom typography, gradients)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    /* Main app background */
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(1200px 800px at 80% -10%, rgba(99, 102, 241, 0.18), transparent 60%),
            radial-gradient(1000px 700px at -10% 110%, rgba(192, 132, 252, 0.14), transparent 60%),
            linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
        color: #f8fafc;
    }
    
    [data-testid="stHeader"] {
        background: transparent;
    }
    
    /* Sidebar glass panel */
    [data-testid="stSidebar"] {
        background: rgba(15, 23, 42, 0.9);
        border-right: 1px solid rgba(255, 255, 255, 0.08);
        backdrop-filter: blur(10px);
    }
    
    [data-testid="stSidebar"] .stMarkdown h3 {
        color: #a5b4fc;
    }
    
    /* Chat input */
    [data-testid="stChatInput"] {
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        background: rgba(30, 41, 59, 0.9);
    }
    
    [data-testid="stChatInput"]:focus-within {
        border-color: #6366f1;
        box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.3);
    }
    
    /* Chat scroll container panel */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 10px;
    }
    
    /* Chat messages */
    [data-testid="stChatMessage"] {
        padding: 0;
        margin-bottom: 10px;
    }
    
    [data-testid="stChatMessageContent"] {
        width: fit-content;
        max-width: 85%;
        flex-grow: 0;
        margin: 0;
        line-height: 1.5;
        padding: 10px 14px;
        border-radius: 16px;
    }
    
    /* User message: bubble on the right */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        flex-direction: row-reverse;
        justify-content: flex-start;
        background: transparent !important;
    }
    [data-testid="stChatMessageAvatarUser"] {
        background: #22c55e !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: #ffffff;
        border-bottom-right-radius: 4px;
    }
    
    /* Bot message: bubble on the left */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
        background: rgba(30, 41, 59, 0.95);
        color: #f8fafc;
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-left: 3px solid #6366f1;
        border-bottom-left-radius: 4px;
    }
    
    /* Intent pill */
    .intent-pill {
        display: inline-block;
        margin-top: 6px;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 600;
        color: #a5b4fc;
        background: rgba(99, 102, 241, 0.15);
        border: 1px solid rgba(99, 102, 241, 0.35);
    }
    
    .title-gradient {
        background: linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 3rem !important;
        margin-bottom: 0.5rem;
    }
    
    .subtitle {
        color: #94a3b8;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    
    /* Custom ticket card styling */
    .ticket-card {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 15px;
        transition: transform 0.2s, border-color 0.2s;
        backdrop-filter: blur(10px);
    }
    
    .ticket-card:hover {
        transform: translateY(-2px);
        border-color: rgba(99, 102, 241, 0.6);
        box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
    }
    
    .ticket-title {
        font-size: 1.25rem;
        font-weight: 600;
        color: #f8fafc;
        margin-bottom: 8px;
    }
    
    .ticket-meta {
        font-size: 0.9rem;
        color: #94a3b8;
        margin-bottom: 12px;
    }
    
    .ticket-price {
        font-size: 1.4rem;
        font-weight: 700;
        color: #38bdf8;
    }
    
    .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        margin-left: 8px;
    }
    
    .badge-music { background: rgba(56, 189, 248, 0.2); color: #38bdf8; }
    .badge-theater { background: rgba(192, 132, 252, 0.2); color: #c084fc; }
    .badge-sports { background: rgba(248, 113, 113, 0.2); color: #f87171; }
    .badge-comedy { background: rgba(74, 222, 128, 0.2); color: #4ade80; }
    
    .status-online {
        color: #4ade80;
        font-weight: 600;
    }
    .status-offline {
        color: #f87171;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Generate or retrieve session ID
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())[:8]

# Initialize messages list
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# Title Section
st.markdown("<h1 class='title-gradient'>Online Ticketing Chatbot System</h1>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Side-by-side NLU comparison of Online Ticketing Chatbots (Rasa vs Custom NLP vs Dialogflow)</div>", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.image("https://img.icons8.com/clouds/200/000000/ticket.png", width=120)
    st.markdown("### Configuration")
    
    # Check backend status
    backend_online = False
    try:
        response = requests.get(f"{BACKEND_URL}/api/tickets", timeout=5)
        if response.status_code == 200:
            backend_online = True
    except Exception:
        pass
        
    if backend_online:
        st.markdown("Backend Status: <span class='status-online'>● ONLINE</span>", unsafe_allow_html=True)
    else:
        st.markdown("Backend Status: <span class='status-offline'>● OFFLINE (Run fastapi first)</span>", unsafe_allow_html=True)
    
    bot_choice = st.selectbox(
        "Select Chatbot NLU Engine",
        ["Rasa", "NLP (Custom ML)", "Dialogflow"],
        help="Compare Rasa, custom machine learning NLU, and Google Dialogflow side-by-side."
    )
    
    bot_map = {
        "Rasa": "rasa",
        "NLP (Custom ML)": "nlp",
        "Dialogflow": "dialogflow"
    }
    selected_bot = bot_map[bot_choice]

    # Clear chat history when switching bots
    if "previous_bot" not in st.session_state:
        st.session_state["previous_bot"] = selected_bot

    if st.session_state["previous_bot"] != selected_bot:
        st.session_state["messages"] = []
        st.session_state["session_id"] = str(uuid.uuid4())[:8]
        st.session_state["previous_bot"] = selected_bot
    
    st.markdown("---")
    st.markdown("### Share Feedback")
    st.write("Rate your conversation with the selected bot:")
    
    rating = st.slider("Rating", min_value=1, max_value=5, value=5)
    comment = st.text_area("Review Comment", placeholder="e.g., Fast responses, recognized my intent correctly.")
    
    if st.button("Submit Review"):
        if backend_online:
            feedback_payload = {
                "session_id": st.session_state["session_id"],
                "bot_type": selected_bot,
                "rating": rating,
                "comment": comment
            }
            try:
                res = requests.post(f"{BACKEND_URL}/api/feedback", json=feedback_payload)
                if res.status_code == 200:
                    st.success("Thank you for your feedback!")
                else:
                    st.error("Failed to submit feedback.")
            except Exception as e:
                st.error(f"Error connecting to backend: {e}")
        else:
            st.warning("Backend offline. Cannot save feedback.")

# Display contents in a nice layout
col1, col2 = st.columns([1, 2])

with col1:
    st.markdown("### 🎟️ Event Tickets Catalog")
    if not backend_online:
        st.info("Start the FastAPI backend to load live ticket data.")
        st.markdown("""
        <div class='ticket-card'>
            <div class='ticket-title'>Mock Concert A <span class='badge badge-music'>Music</span></div>
            <div class='ticket-meta'>Date: 2026-05-20 | Venue: Stadium XYZ | Available: 120</div>
            <div class='ticket-price'>RM150.00</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        try:
            tickets = requests.get(f"{BACKEND_URL}/api/tickets").json()
            if not tickets:
                st.info("No tickets seeded. Press 'Seed DB' in backend.")
                if st.button("Seed Database Now"):
                    requests.post(f"{BACKEND_URL}/api/seed")
                    st.rerun()
            for t in tickets:
                category = t['category']
                st.markdown(f"""
                <div class='ticket-card'>
                    <div class='ticket-title'>{t['event']} <span class='badge badge-{category}'>{category}</span></div>
                    <div class='ticket-meta'>Date: {t['date']} | Venue: {t['venue']} | Available: {t['available']}</div>
                    <div class='ticket-price'>RM{t['price']:.2f}</div>
                </div>
                """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Error retrieving tickets: {e}")

with col2:
    st.markdown(f"### 💬 Chat with {bot_choice} Bot")
    
    # Scrollable chat history container (tall enough to show plenty of history)
    chat_container = st.container(height=500)
    
    with chat_container:
        for msg in st.session_state["messages"]:
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant":
                    text = msg["text"]
                    text = text.replace("\n\n", "\x00").replace("\n", "  \n").replace("\x00", "\n\n")
                    st.write(text)
                else:
                    st.write(msg["text"])
                if msg["role"] == "assistant" and "intent" in msg and msg["intent"]:
                    st.markdown(
                        f"<span class='intent-pill'>Intent: {msg['intent']} · {msg['confidence']:.1%}</span>",
                        unsafe_allow_html=True,
                    )

    # Input text box
    user_input = st.chat_input("Type a message to book tickets, check availability, or greet the bot...")
    
    if user_input:
        # Append User message to history
        st.session_state["messages"].append({"role": "user", "text": user_input})
        
        # Send message to backend API
        bot_response = f"Could not connect to backend server at {BACKEND_URL}."
        intent = None
        confidence = None
        
        if backend_online:
            try:
                chat_payload = {
                    "message": user_input,
                    "bot": selected_bot,
                    "session_id": st.session_state["session_id"]
                }
                res = requests.post(f"{BACKEND_URL}/api/chat", json=chat_payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    bot_response = data["response"]
                    intent = data.get("intent")
                    confidence = data.get("confidence")
            except Exception as e:
                bot_response = f"API Error: {e}"
        else:
            # The sidebar check may be stale; always try the chat endpoint anyway.
            try:
                chat_payload = {
                    "message": user_input,
                    "bot": selected_bot,
                    "session_id": st.session_state["session_id"]
                }
                res = requests.post(f"{BACKEND_URL}/api/chat", json=chat_payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    bot_response = data["response"]
                    intent = data.get("intent")
                    confidence = data.get("confidence")
                else:
                    bot_response = f"Backend API error: {res.status_code}"
            except Exception as e:
                bot_response = f"Could not connect to backend server at {BACKEND_URL}."
        
        # Append Bot message to history
        st.session_state["messages"].append({
            "role": "assistant",
            "text": bot_response,
            "intent": intent,
            "confidence": confidence
        })
        
        # Force refresh to show bot response
        st.rerun()
