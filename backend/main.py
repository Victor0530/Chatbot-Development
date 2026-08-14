import uuid
import requests
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import List

from models import ChatRequest, ChatResponse, FeedbackRequest, Ticket
from database import get_collection
from dialogflow.dialogflow_bot import handle_dialogflow_message

app = FastAPI(title="Unified Chatbot Ticketing API", version="1.0")

# Enable CORS for Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/tickets", response_model=List[Ticket])
def get_tickets():
    tickets_col = get_collection("tickets")
    tickets = tickets_col.find()
    # Remove _id mongo field if present or parse it to fit Pydantic model
    parsed_tickets = []
    for t in tickets:
        parsed_tickets.append(Ticket(
            event=t.get("event"),
            date=t.get("date"),
            venue=t.get("venue"),
            price=t.get("price"),
            available=t.get("available"),
            category=t.get("category")
        ))
    return parsed_tickets

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest):
    message = payload.message.strip()
    bot = payload.bot.lower()
    session_id = payload.session_id or str(uuid.uuid4())[:8]

    if bot not in ["rasa", "nlp", "dialogflow"]:
        raise HTTPException(status_code=400, detail="Invalid bot type. Choose rasa, nlp, or dialogflow.")
        
    # Initialize defaults
    intent = "unknown"
    confidence = 0.0
    response_text = "I'm sorry, I couldn't process your request."
    
    # Phase 2: Actual Rasa Integration
    if bot == "rasa":
        try:
            rasa_payload = {"sender": payload.session_id or "user", "message": message}

            # Get intent via /model/parse
            parse_response = requests.post("http://rasa:5005/model/parse", json={"text": message}, timeout=20)
            if parse_response.status_code == 200:
                parse_data = parse_response.json()
                intent = parse_data.get("intent", {}).get("name", "unknown")
                confidence = parse_data.get("intent", {}).get("confidence", 0.0)

            # Get response text via /webhooks/rest/webhook
            response = requests.post("http://rasa:5005/webhooks/rest/webhook", json=rasa_payload, timeout=20)
            if response.status_code == 200:
                data = response.json()
                if data:
                    response_text = "\n\n".join([msg.get("text", "") for msg in data])
                else:
                    if any(keyword in message.lower() for keyword in ["buy", "ticket", "book", "hi", "hello"]):
                        response_text = "Which event are you interested in?"
                    else:
                        response_text = "I understood you, but have no response."
            else:
                response_text = f"Rasa API error: {response.status_code}"
        except Exception as e:
            response_text = f"Could not connect to Rasa: {e}"
    elif bot == "nlp":
        try:
            # The nlp-chatbot container is reachable via its service name 'nlp-chatbot'
            response = requests.post("http://nlp-chatbot:8600/chat", json={"message": message, "session_id": session_id}, timeout=20)
            if response.status_code == 200:
                data = response.json()
                response_text = data.get("response", response_text)
                intent = data.get("intent") or intent
                confidence = data.get("confidence") or confidence
            else:
                response_text = f"NLP chatbot error: {response.status_code}"
        except Exception as e:
            response_text = f"Could not connect to NLP chatbot: {e}"
    elif bot == "dialogflow":
        response_text, intent, confidence = handle_dialogflow_message(payload.session_id or "default", message)
        
    # Log conversation to database
    conversations_col = get_collection("conversations")

    conversations_col.insert_one({
        "session_id": session_id,
        "bot_type": bot,
        "messages": [
            { "role": "user", "text": message, "timestamp": datetime.utcnow().isoformat() },
            { "role": "bot", "text": response_text, "timestamp": datetime.utcnow().isoformat() }
        ],
        "intents": [intent],
        "created_at": datetime.utcnow().isoformat()
    })
    
    return ChatResponse(
        response=response_text,
        intent=intent,
        confidence=confidence
    )

@app.post("/api/feedback")
def submit_feedback(payload: FeedbackRequest):
    feedback_col = get_collection("feedback")
    feedback_col.insert_one({
        "session_id": payload.session_id,
        "bot_type": payload.bot_type,
        "rating": payload.rating,
        "comment": payload.comment,
        "created_at": datetime.utcnow().isoformat()
    })
    return {"status": "success", "message": "Feedback submitted successfully."}

@app.post("/api/seed")
def trigger_seed():
    try:
        from seed import seed_db
        seed_db()
        return {"status": "success", "message": "Database seeded successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
