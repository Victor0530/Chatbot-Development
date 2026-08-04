"""Multi-turn ticket booking: session state machine + real MongoDB actions.

Kept self-contained here rather than in the shared backend, mirroring how
rasa-chatbot/actions/actions.py owns its own booking logic and its own
direct MongoDB connection. The classifier in src/chatbot.py only ever
needs to recognize the initial "book_ticket" intent; everything after that
(remembering which event/quantity we're waiting on, validating against live
stock, writing the booking) happens here.
"""
import os
import re
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "chatbot_ticketing")

WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "a": 1, "an": 1, "couple": 2, "few": 3,
}

CANCEL_WORDS = {"cancel", "stop", "never mind", "nevermind"}

_client: Optional[MongoClient] = None
# session_id -> {"event_name": str | None, "awaiting": "event_name" | "ticket_quantity"}
_sessions: dict[str, dict] = {}


def _get_db():
    global _client
    if not MONGO_URI:
        return None
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]


def parse_quantity(text: str) -> Optional[int]:
    text = text.lower().strip()
    try:
        qty = int(text)
        return qty if qty > 0 else None
    except ValueError:
        pass
    if text in WORD_TO_NUM:
        return WORD_TO_NUM[text]
    digits = re.findall(r"\d+", text)
    return int(digits[0]) if digits else None


def has_active_session(session_id: str) -> bool:
    return session_id in _sessions


def start_session(session_id: str) -> None:
    _sessions[session_id] = {"event_name": None, "awaiting": "event_name"}


def handle_turn(session_id: str, message: str) -> tuple[str, str]:
    """Advance the booking state machine one turn. Returns (response_text, intent_label)."""
    if message.lower().strip().strip("?!.") in CANCEL_WORDS:
        _sessions.pop(session_id, None)
        return "No problem, I've cancelled the booking.", "book_ticket_cancelled"

    db = _get_db()
    if db is None:
        _sessions.pop(session_id, None)
        return (
            "Sorry, the booking service is temporarily unavailable. Please try again in a moment.",
            "book_ticket_unavailable",
        )

    session = _sessions[session_id]
    try:
        if session["awaiting"] == "event_name":
            return _handle_event_name(db, session, message)
        return _handle_quantity(db, session_id, session, message)
    except PyMongoError:
        _sessions.pop(session_id, None)
        return (
            "Sorry, I couldn't reach the booking database. Please try again in a moment.",
            "book_ticket_unavailable",
        )


def _handle_event_name(db, session: dict, message: str) -> tuple[str, str]:
    ticket = db.tickets.find_one({"event": {"$regex": re.escape(message.strip()), "$options": "i"}})
    if not ticket:
        events = ", ".join(t["event"] for t in db.tickets.find())
        return (
            f"I couldn't find an event matching '{message}'. Available events: {events or 'none'}.",
            "book_ticket_awaiting_event",
        )
    session["event_name"] = ticket["event"]
    session["awaiting"] = "ticket_quantity"
    return f"Great, {ticket['event']}! How many tickets would you like?", "book_ticket_awaiting_quantity"


def _handle_quantity(db, session_id: str, session: dict, message: str) -> tuple[str, str]:
    qty = parse_quantity(message)
    if qty is None:
        return (
            "I couldn't understand the number of tickets. Could you specify a number?",
            "book_ticket_awaiting_quantity",
        )

    ticket = db.tickets.find_one({"event": session["event_name"]})
    if not ticket or ticket["available"] < qty:
        available = ticket["available"] if ticket else 0
        return (
            f"Sorry, only {available} tickets left for {session['event_name']}. How many would you like?",
            "book_ticket_awaiting_quantity",
        )

    db.bookings.insert_one({
        "event": ticket["event"],
        "quantity": qty,
        "session_id": session_id,
        "status": "booked",
    })
    db.tickets.update_one({"_id": ticket["_id"]}, {"$inc": {"available": -qty}})
    _sessions.pop(session_id, None)
    return f"Success! Booked {qty} ticket(s) for {ticket['event']}.", "book_ticket_confirmed"
