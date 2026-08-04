"""Two-turn lookups for check_price / event_schedule / event_location: ask
for the event name, then answer from the tickets collection.

Mirrors booking.py's session pattern, but simpler - there's only ever one
pending question (the event name), so a session is just the intent tag
waiting on an answer rather than a multi-state machine.
"""
import os
import re
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "chatbot_ticketing")

CANCEL_WORDS = {"cancel", "stop", "never mind", "nevermind"}

LOOKUP_INTENTS = {"check_price", "event_schedule", "event_location"}

_ANSWER_BUILDERS = {
    "check_price": lambda t: f"{t['event']} costs ${t['price']:.2f}, with {t['available']} seats left.",
    "event_schedule": lambda t: f"{t['event']} is scheduled for {t['date']}.",
    "event_location": lambda t: f"{t['event']} is held at {t['venue']}.",
}

_client: Optional[MongoClient] = None
# session_id -> pending intent tag
_sessions: dict[str, str] = {}


def _get_db():
    global _client
    if not MONGO_URI:
        return None
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]


def has_active_session(session_id: str) -> bool:
    return session_id in _sessions


def start_session(session_id: str, intent: str) -> None:
    _sessions[session_id] = intent


def handle_turn(session_id: str, message: str) -> tuple[str, str]:
    """Resolve the pending lookup with the event name just given. Returns (response_text, intent_label)."""
    intent = _sessions.pop(session_id)

    if message.lower().strip().strip("?!.") in CANCEL_WORDS:
        return "No problem, let me know if you need anything else.", f"{intent}_cancelled"

    db = _get_db()
    if db is None:
        return (
            "Sorry, the lookup service is temporarily unavailable. Please try again in a moment.",
            f"{intent}_unavailable",
        )

    try:
        ticket = db.tickets.find_one({"event": {"$regex": re.escape(message.strip()), "$options": "i"}})
    except PyMongoError:
        return (
            "Sorry, I couldn't reach the database. Please try again in a moment.",
            f"{intent}_unavailable",
        )

    if not ticket:
        events = ", ".join(t["event"] for t in db.tickets.find())
        return (
            f"I couldn't find an event matching '{message}'. Available events: {events or 'none'}.",
            f"{intent}_not_found",
        )

    return _ANSWER_BUILDERS[intent](ticket), f"{intent}_answered"
