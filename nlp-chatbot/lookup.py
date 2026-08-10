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

# Mirrors booking.py's ESCAPE_CONFIDENCE_THRESHOLD - how sure the ML
# classifier has to be about a different intent before a message that
# didn't name a known event is treated as a topic change rather than just a
# bad answer to "which event?".
ESCAPE_CONFIDENCE_THRESHOLD = 0.5

LOOKUP_INTENTS = {"check_price", "event_schedule", "event_location"}

_ANSWER_BUILDERS = {
    "check_price": lambda t: f"{t['event']} costs ${t['price']:.2f}, with {t['available']} seats left.",
    "event_schedule": lambda t: f"{t['event']} is scheduled for {t['date']}.",
    "event_location": lambda t: f"{t['event']} is held at {t['venue']}.",
}

_client: Optional[MongoClient] = None
# session_id -> pending intent tag
_sessions: dict[str, str] = {}
# session_id -> name of the event last resolved for this session, so a
# follow-up like "at what place?" can reuse it instead of asking again.
_last_event: dict[str, str] = {}
# session_id -> which of LOOKUP_INTENTS was last resolved, so a follow-up
# that only names a *different* event ("how about Concert B") can reuse the
# same question instead of falling through to a generic fallback reply.
_last_intent: dict[str, str] = {}


def _get_db():
    global _client
    if not MONGO_URI:
        return None
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]


def list_events() -> str:
    """Build a live list of bookable events from the tickets collection."""
    db = _get_db()
    if db is None:
        return "Sorry, the event list is temporarily unavailable. Please try again in a moment."
    try:
        events = ", ".join(t["event"] for t in db.tickets.find())
    except PyMongoError:
        return "Sorry, I couldn't reach the database. Please try again in a moment."
    if not events:
        return "There are no events open for booking right now."
    return f"We currently have tickets available for: {events}. Which one would you like to know more about?"


def has_active_session(session_id: str) -> bool:
    return session_id in _sessions


def start_session(session_id: str, intent: str) -> None:
    _sessions[session_id] = intent


def get_last_event(session_id: str) -> Optional[str]:
    """The event this session was last talking about, if any - lets other
    flows (like booking.py starting a book_ticket session) carry it over
    instead of asking the user to repeat the event name."""
    return _last_event.get(session_id)


def find_event_in_message(message: str) -> Optional[str]:
    """Look for a known event name mentioned in `message` itself, with no
    session state involved. Covers replies like "Concert A" sent right after
    list_events - lookup never got a chance to record that event as this
    session's context (list_events doesn't call try_answer/start_session),
    so get_last_event() alone would miss it and the caller would re-ask for
    an event name the user already gave."""
    db = _get_db()
    if db is None:
        return None
    try:
        ticket = _find_ticket(db, message)
    except PyMongoError:
        return None
    return ticket["event"] if ticket else None


def _word_match(needle: str, haystack: str) -> bool:
    """Whether `needle` appears in `haystack` as whole words, not just as a
    raw substring - a raw `in` check lets short words match inside an
    unrelated longer word (e.g. "ship" inside "championship")."""
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def _matching_tickets(db, text: str) -> list[dict]:
    """All tickets whose event name is referenced in `text`, either as a
    short reply ("Concert A", "broadway") or embedded in a full sentence
    ("what's the price of Broadway Musical"). Matches in both directions so
    both styles work, but only on whole-word/phrase boundaries. Messages
    under 3 chars are skipped to avoid trivial false positives (e.g. "at"
    matching nothing sensible). Can return more than one ticket when the
    text is genuinely ambiguous (e.g. "concert" matches both Concert A and
    Concert B) - callers decide whether to disambiguate or just treat that
    the same as no match."""
    text_lower = text.strip().lower()
    if len(text_lower) < 3:
        return []
    matches = []
    for t in db.tickets.find():
        event_lower = t["event"].lower()
        short_lower = t["event"].split(" - ")[0].lower()
        if (
            _word_match(short_lower, text_lower)
            or _word_match(event_lower, text_lower)
            or _word_match(text_lower, event_lower)
        ):
            matches.append(t)
    return matches


def _find_ticket(db, text: str) -> Optional[dict]:
    """A single unambiguous ticket match, or None if `text` matched no event
    or matched more than one (see _matching_tickets for the ambiguous case;
    describe_match_failure() turns that into a clarifying message instead of
    a flat "not found")."""
    matches = _matching_tickets(db, text)
    return matches[0] if len(matches) == 1 else None


def describe_match_failure(db, text: str) -> str:
    """The right fallback message for a failed event lookup: name the
    candidates when `text` was ambiguous between more than one event, or
    list every bookable event when it matched none at all."""
    matches = _matching_tickets(db, text)
    if len(matches) > 1:
        names = ", ".join(t["event"] for t in matches)
        return f"I found more than one event matching '{text}': {names}. Which one did you mean?"
    events = ", ".join(t["event"] for t in db.tickets.find())
    return f"I couldn't find an event matching '{text}'. Available events: {events or 'none'}."


def try_answer(session_id: str, intent: str, message: str) -> Optional[tuple[str, str]]:
    """Answer immediately if the message names an event, or if this session
    was already talking about one (e.g. "at what place?" right after a
    check_price answer). Returns None if neither applies, so the caller
    should fall back to start_session() and ask which event."""
    db = _get_db()
    if db is None:
        return None

    try:
        ticket = _find_ticket(db, message)
        if ticket is None and session_id in _last_event:
            ticket = db.tickets.find_one({"event": _last_event[session_id]})
    except PyMongoError:
        return None

    if ticket is None:
        return None

    _last_event[session_id] = ticket["event"]
    _last_intent[session_id] = intent
    return _ANSWER_BUILDERS[intent](ticket), f"{intent}_answered"


def try_continue(session_id: str, message: str) -> Optional[tuple[str, str]]:
    """Fallback for messages like "how about Concert B" - they name an event
    but carry no lexical signal for *which* lookup intent is meant, so the
    classifier lands on an unrelated intent (bot_capabilities, greeting...).
    If this session already has a lookup intent in flight, reuse it rather
    than replying with whatever the misclassification produced. Only the
    caller should decide when a misclassification is likely enough to try
    this (see api.py's _NON_TICKET_INTENTS check)."""
    intent = _last_intent.get(session_id)
    if intent is None:
        return None

    db = _get_db()
    if db is None:
        return None

    try:
        ticket = _find_ticket(db, message)
    except PyMongoError:
        return None

    if ticket is None:
        return None

    _last_event[session_id] = ticket["event"]
    return _ANSWER_BUILDERS[intent](ticket), f"{intent}_answered"


def handle_turn(
    session_id: str,
    message: str,
    intent_hint: Optional[str] = None,
    confidence_hint: float = 0.0,
) -> Optional[tuple[str, str]]:
    """Resolve the pending lookup with the event name just given. Returns
    (response_text, intent_label), or None if no event matched *and* the
    message reads as a confident, different intent per
    `intent_hint`/`confidence_hint` - the caller (api.py) should then route
    the message fresh instead of getting an unhelpful "couldn't find that
    event" reply to a question that was never about an event at all."""
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
        ticket = _find_ticket(db, message)
    except PyMongoError:
        return (
            "Sorry, I couldn't reach the database. Please try again in a moment.",
            f"{intent}_unavailable",
        )

    if not ticket:
        if intent_hint is not None and confidence_hint >= ESCAPE_CONFIDENCE_THRESHOLD:
            return None
        return describe_match_failure(db, message), f"{intent}_not_found"

    _last_event[session_id] = ticket["event"]
    _last_intent[session_id] = intent
    return _ANSWER_BUILDERS[intent](ticket), f"{intent}_answered"
