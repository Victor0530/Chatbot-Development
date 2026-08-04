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

# Intents that have nothing to do with a specific ticket. If the classifier
# lands here *and* the message names a known event ("how about Concert B"
# right after a price/schedule/location question), it's more likely a
# misclassification than an actual topic change - lookup.try_continue()
# reuses the session's last lookup intent instead.
_NON_TICKET_INTENTS = {None, "greeting", "bot_capabilities", "thanks", "goodbye"}


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

    intent, confidence = _chatbot.resolve_intent(payload.message)
    response_text = _chatbot.get_response(payload.message)

    if intent == "book_ticket":
        started = booking.start_session(payload.session_id, lookup.get_last_event(payload.session_id))
        if started is not None:
            response_text, intent = started
    elif intent in lookup.LOOKUP_INTENTS:
        answered = lookup.try_answer(payload.session_id, intent, payload.message)
        if answered is not None:
            response_text, intent = answered
        else:
            lookup.start_session(payload.session_id, intent)
    elif intent == "list_events":
        response_text = lookup.list_events()
    elif intent in _NON_TICKET_INTENTS:
        continued = lookup.try_continue(payload.session_id, payload.message)
        if continued is not None:
            response_text, intent = continued

    return ChatOut(response=response_text, intent=intent, confidence=confidence)
