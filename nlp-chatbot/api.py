"""FastAPI wrapper exposing the ML/NLP chatbot (src/chatbot.py) over HTTP,
so the backend can call it the same way it calls the Rasa service.

Run with:
    uvicorn api:app --host 0.0.0.0 --port 8600
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import booking
import lookup
from src.chatbot import ChatBot, strip_greeting_prefix

app = FastAPI(title="NLP (ML) Chatbot API", version="1.0")

_chatbot: ChatBot | None = None

# Intents that have nothing to do with a specific ticket. If the classifier
# lands here *and* the message names a known event ("how about Concert B"
# right after a price/schedule/location question), it's more likely a
# misclassification than an actual topic change - lookup.try_continue()
# reuses the session's last lookup intent instead.
_NON_TICKET_INTENTS = {None, "greeting", "bot_capabilities", "thanks", "goodbye"}

# Intents whose canned response is already apologetic/declining
# (cancel_ticket's "Sorry, this assistant can't process cancellations
# yet...") - prepending a cheerful "Hi there!" to those reads as tonally
# contradictory, so the greeting-prefix cosmetic below skips them even when
# the message did open with a greeting.
_APOLOGETIC_INTENTS = {"cancel_ticket"}


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

    if _chatbot is None:
        try:
            _chatbot = ChatBot("svm")
        except FileNotFoundError:
            raise HTTPException(
                status_code=503,
                detail="Model not trained yet. Run 'docker compose exec nlp-chatbot python train.py' "
                       "then 'docker compose restart nlp-chatbot'.",
            )

    session_id, message = payload.session_id, payload.message

    # Mid-booking/mid-lookup: the message is normally an answer to a pending
    # slot (event name, quantity, yes/no), not a fresh message to classify.
    # We still classify it here so that if it *doesn't* answer what's being
    # asked, handle_turn can tell a genuine topic change (confident
    # intent_hint) from just a bad/garbled answer, and bail out of the stuck
    # flow into the normal routing below rather than repeating the same
    # prompt forever.
    if booking.has_active_session(session_id) or lookup.has_active_session(session_id):
        intent_hint, confidence_hint = _chatbot.resolve_intent(message)
        if booking.has_active_session(session_id):
            result = booking.handle_turn(session_id, message, intent_hint, confidence_hint)
        else:
            result = lookup.handle_turn(session_id, message, intent_hint, confidence_hint)
        if result is not None:
            response_text, intent = result
            return ChatOut(response=response_text, intent=intent, confidence=1.0)
        intent, confidence = intent_hint, confidence_hint
    else:
        intent, confidence = _chatbot.resolve_intent(message)

    response_text = _chatbot.get_response(message)

    # In several branches below, `intent` gets reassigned to a label a
    # deterministic DB-lookup/state-machine function produced instead of the
    # classifier's original tag (e.g. "book_ticket" ->
    # "book_ticket_awaiting_quantity", "check_price" -> "check_price_answered").
    # `confidence` is reset to 1.0 alongside each such reassignment, for the
    # same reason the mid-session path above already returns 1.0: once the
    # reply comes from a confirmed DB match rather than the classifier's
    # guess, the classifier's original confidence on the raw message no
    # longer describes what's actually being returned.
    if intent == "book_ticket":
        carried_event = lookup.get_last_event(session_id) or lookup.find_event_in_message(message)
        started = booking.start_session(session_id, carried_event, message)
        if started is not None:
            response_text, intent = started
            confidence = 1.0
    elif intent in lookup.LOOKUP_INTENTS:
        answered = lookup.try_answer(session_id, intent, message)
        if answered is not None:
            response_text, intent = answered
            confidence = 1.0
        else:
            # "which events are held at Grand Theater" also lands here (it
            # shares "event"/"venue" vocabulary with the usual "where is the
            # event held" phrasing) - the message names a venue, not an
            # event, so answer the reverse lookup instead of asking "which
            # event's location?" to a question that already named a venue.
            venue_tickets = lookup.find_tickets_by_venue(message) if intent == "event_location" else []
            if venue_tickets:
                response_text = lookup.describe_events_at_venue(venue_tickets)
                intent = "events_by_venue_answered"
                confidence = 1.0
            else:
                lookup.start_session(session_id, intent)
    elif intent == "list_events":
        response_text = lookup.list_events(message)
        booking.start_selection_session(session_id)
    elif intent in _NON_TICKET_INTENTS:
        continued = lookup.try_continue(session_id, message)
        if continued is not None:
            response_text, intent = continued
            confidence = 1.0

    # A leading "Hi,"/"Hello there," on an otherwise substantive message
    # (e.g. "Hi, what events do you have") stays polite without letting the
    # greeting hijack the whole reply the way it used to: resolve_intent()
    # already routes on the *substantive* intent, so this just prepends an
    # acknowledgement rather than answering with a bare greeting instead of
    # the actual request. Skipped when intent is "greeting" itself - a bare
    # "Hello" already gets its own greeting response, no need to double it -
    # and skipped for _APOLOGETIC_INTENTS for the tonal-clash reason above.
    if (
        intent != "greeting"
        and intent not in _APOLOGETIC_INTENTS
        and strip_greeting_prefix(message) is not None
    ):
        response_text = f"Hi there! {response_text}"

    return ChatOut(response=response_text, intent=intent, confidence=confidence)
