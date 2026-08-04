"""FastAPI wrapper exposing the ML/NLP chatbot (src/chatbot.py) over HTTP,
so the backend can call it the same way it calls the Rasa service.

Run with:
    uvicorn api:app --host 0.0.0.0 --port 8600
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import booking
import lookup
from src.chatbot import ChatBot

app = FastAPI(title="NLP (ML) Chatbot API", version="1.0")

_chatbot: ChatBot | None = None


class ChatIn(BaseModel):
    message: str
    session_id: str = "default"


class ChatOut(BaseModel):
    response: str
    intent: str | None = None
    confidence: float | None = None


@app.post("/chat", response_model=ChatOut)
def chat(payload: ChatIn):
    global _chatbot

    # Mid-booking: the message is an answer to a pending slot (event name or
    # quantity), not a fresh message to classify.
    if booking.has_active_session(payload.session_id):
        response_text, intent = booking.handle_turn(payload.session_id, payload.message)
        return ChatOut(response=response_text, intent=intent, confidence=1.0)

    # Mid-lookup: the message is the event name we asked for, not a fresh
    # message to classify.
    if lookup.has_active_session(payload.session_id):
        response_text, intent = lookup.handle_turn(payload.session_id, payload.message)
        return ChatOut(response=response_text, intent=intent, confidence=1.0)

    if _chatbot is None:
        try:
            _chatbot = ChatBot("svm")
        except FileNotFoundError:
            raise HTTPException(
                status_code=503,
                detail="Model not trained yet. Run 'docker compose exec nlp-chatbot python train.py' "
                       "then 'docker compose restart nlp-chatbot'.",
            )

    intent, confidence = _chatbot.predict_intent(payload.message)
    response_text = _chatbot.get_response(payload.message)

    if intent == "book_ticket":
        booking.start_session(payload.session_id)
    elif intent in lookup.LOOKUP_INTENTS:
        lookup.start_session(payload.session_id, intent)

    return ChatOut(response=response_text, intent=intent, confidence=confidence)
