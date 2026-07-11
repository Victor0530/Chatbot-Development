import uuid
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import List

from models import ChatRequest, ChatResponse, FeedbackRequest, Ticket
from database import get_collection

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
    
    if bot not in ["rasa", "nlp", "dialogflow"]:
        raise HTTPException(status_code=400, detail="Invalid bot type. Choose rasa, nlp, or dialogflow.")
        
    # Phase 1: Mock/Temporary replies from chatbots
    # This acts as our routing placeholder for Phase 2
    bot_responses = {
        "rasa": f"[Rasa Bot (Mock)]: I received your message: '{message}'. Rasa NLU is preparing to book your tickets!",
        "nlp": f"[NLP Model Bot (Mock)]: Processing intent for '{message}'. TF-IDF classification indicates a ticketing query.",
        "dialogflow": f"[Dialogflow Bot (Mock)]: Google Cloud Dialogflow heard: '{message}'. Agent fulfillment is pending."
    }
    
    response_text = bot_responses[bot]
    
    # Logic to match simple greeting or ticket list if the user asks
    lower_message = message.lower()
    intent = "unknown"
    confidence = 0.50
    
    if any(greet in lower_message for greet in ["hi", "hello", "hey"]):
        response_text = f"Hello! I am the {bot.upper()} ticketing bot. How can I help you book tickets today?"
        intent = "greet"
        confidence = 0.95
    elif any(kw in lower_message for kw in ["ticket", "show", "event", "concert", "play", "price"]):
        tickets_col = get_collection("tickets")
        tickets = tickets_col.find()
        ticket_list = ", ".join([t.get("event") for t in tickets])
        response_text = f"Here are the active events we have: {ticket_list}. Which one would you like to book?"
        intent = "query_tickets"
        confidence = 0.90
        
    # Log conversation to database
    conversations_col = get_collection("conversations")
    session_id = payload.session_id or str(uuid.uuid4())[:8]
    
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
