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

import lookup

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "chatbot_ticketing")

WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "a": 1, "an": 1, "couple": 2, "few": 3,
}

CANCEL_WORDS = {"cancel", "stop", "never mind", "nevermind"}
AFFIRMATIVE_PREFIXES = ("yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please", "book")
NEGATIVE_PREFIXES = ("no", "nah", "nope", "not now", "not interested")

_client: Optional[MongoClient] = None
# session_id -> {"event_name": str | None, "awaiting": "event_name" | "event_selection"
#                | "confirm_booking" | "ticket_quantity"}
_sessions: dict[str, dict] = {}


def _get_db():
    global _client
    if not MONGO_URI:
        return None
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]


def parse_quantity(text: str, allow_implicit_one: bool = True) -> Optional[int]:
    """Extract a ticket count from `text`. `allow_implicit_one` gates the
    "a"/"an" heuristic below - it should stay on when parsing an actual
    answer to "how many tickets would you like?" ("a ticket please" clearly
    means 1), but start_session() turns it off when scanning the message
    that *triggered* booking in the first place: nearly every book_ticket
    training pattern reads "book **a ticket** for X" / "reserve **a seat**",
    so treating that "a" as a deliberate "just one" would silently complete
    a booking for messages that never stated a quantity at all."""
    text = text.lower().strip()
    try:
        qty = int(text)
        return qty if qty > 0 else None
    except ValueError:
        pass
    if text in WORD_TO_NUM:
        return WORD_TO_NUM[text]
    match = re.search(r"\d+(\.\d+)?", text)
    if match:
        if match.group(1):
            # a decimal number ("2.5 tickets") isn't a valid ticket count -
            # reject it rather than silently truncating to the integer part.
            return None
        qty = int(match.group())
        return qty if qty > 0 else None

    # No digits either - check for a spelled-out number word among the
    # tokens ("three tickets please"). Skip "a"/"an" here: as a stand-alone
    # reply "a" clearly means one ticket, but as one word among many ("I
    # don't have a preference") it's too common a word to trust as a count.
    for word in re.findall(r"[a-z]+", text):
        if word in WORD_TO_NUM and word not in ("a", "an"):
            return WORD_TO_NUM[word]

    # "a"/"an" still counts as one, but only right next to "ticket(s)"
    # ("book me a ticket please") - narrow enough to not trigger on "a" as
    # just some other word in the sentence.
    if allow_implicit_one and re.search(r"\b(a|an)\s+tickets?\b", text):
        return 1
    return None


def has_active_session(session_id: str) -> bool:
    return session_id in _sessions


def start_session(
    session_id: str, carried_event: Optional[str] = None, message: str = ""
) -> Optional[tuple[str, str]]:
    """Start a booking session. If carried_event is given (the event this
    session was already talking about via a price/schedule/location lookup,
    or named in this same message), skip straight to asking for quantity
    instead of making the user repeat the event name. If `message` also
    already names a quantity ("book 3 tickets for Concert B"), skip that
    question too and finalize the booking directly instead of asking a
    question the user already answered. Returns None when there's no
    carried event (or it no longer resolves) - the caller then falls back to
    the normal "which event?" flow via handle_turn."""
    if carried_event is None:
        _sessions[session_id] = {"event_name": None, "awaiting": "event_name"}
        return None

    db = _get_db()
    ticket = db.tickets.find_one({"event": carried_event}) if db is not None else None
    if not ticket:
        _sessions[session_id] = {"event_name": None, "awaiting": "event_name"}
        return None

    session = {"event_name": ticket["event"], "awaiting": "ticket_quantity"}
    _sessions[session_id] = session
    qty = parse_quantity(message, allow_implicit_one=False) if message else None
    if qty is not None:
        return _finalize_booking(db, session_id, session, qty)
    return f"Great, {ticket['event']}! How many tickets would you like?", "book_ticket_awaiting_quantity"


def start_selection_session(session_id: str) -> None:
    """Begin the post-list_events flow: the customer was just shown the
    event list and asked "which one would you like to know more about?", so
    the next message names an event, not a fresh intent to classify. That
    message resolves to event details plus a book/don't-book question,
    rather than jumping straight into "how many tickets" like start_session
    does for an explicit book_ticket request."""
    _sessions[session_id] = {"event_name": None, "awaiting": "event_selection"}


def handle_turn(session_id: str, message: str) -> tuple[str, str]:
    """Advance the booking state machine one turn. Returns (response_text, intent_label)."""
    if message.lower().strip().strip("?!.") in CANCEL_WORDS:
        cancelled = _sessions.pop(session_id, None)
        if cancelled is not None and cancelled["awaiting"] in ("event_selection", "confirm_booking"):
            # Nothing was actually being booked yet at these stages - just
            # browsing event details - so "cancelled the booking" would
            # imply a booking that never started.
            return "No problem, let me know if there's anything else I can help you with.", "list_events_cancelled"
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
        if session["awaiting"] == "event_selection":
            return _handle_event_selection(db, session, message)
        if session["awaiting"] == "confirm_booking":
            return _handle_confirm(db, session_id, session, message)
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
    event_name = lookup.find_event_in_message(message)
    ticket = db.tickets.find_one({"event": event_name}) if event_name else None
    if not ticket:
        return lookup.describe_match_failure(db, message), "book_ticket_awaiting_event"
    session["event_name"] = ticket["event"]
    session["awaiting"] = "ticket_quantity"
    return f"Great, {ticket['event']}! How many tickets would you like?", "book_ticket_awaiting_quantity"


def _event_details(ticket: dict) -> str:
    return (
        f"{ticket['event']}: ${ticket['price']:.2f} per ticket, {ticket['available']} seats left, "
        f"on {ticket['date']} at {ticket['venue']}."
    )


def _handle_event_selection(db, session: dict, message: str) -> tuple[str, str]:
    event_name = lookup.find_event_in_message(message)
    ticket = db.tickets.find_one({"event": event_name}) if event_name else None
    if not ticket:
        return lookup.describe_match_failure(db, message), "list_events_not_found"
    session["event_name"] = ticket["event"]
    session["awaiting"] = "confirm_booking"
    return (
        f"{_event_details(ticket)} Would you like to book a ticket for this event?",
        "list_events_selected",
    )


def _handle_confirm(db, session_id: str, session: dict, message: str) -> tuple[str, str]:
    normalized = message.lower().strip().strip("?!.")
    qty = parse_quantity(message)

    if qty is None and normalized.startswith(NEGATIVE_PREFIXES):
        _sessions.pop(session_id, None)
        return "No problem! Let me know if there's anything else I can help you with.", "list_events_declined"

    if qty is not None:
        return _finalize_booking(db, session_id, session, qty)

    if normalized.startswith(AFFIRMATIVE_PREFIXES):
        session["awaiting"] = "ticket_quantity"
        return (
            f"Great! How many tickets would you like for {session['event_name']}?",
            "book_ticket_awaiting_quantity",
        )

    return (
        "Sorry, would you like to book a ticket for this event? (yes/no)",
        "list_events_confirm_retry",
    )


def _handle_quantity(db, session_id: str, session: dict, message: str) -> tuple[str, str]:
    qty = parse_quantity(message)
    if qty is None:
        return (
            "I couldn't understand the number of tickets. Could you specify a number?",
            "book_ticket_awaiting_quantity",
        )
    return _finalize_booking(db, session_id, session, qty)


def _finalize_booking(db, session_id: str, session: dict, qty: int) -> tuple[str, str]:
    ticket = db.tickets.find_one({"event": session["event_name"]})
    if not ticket or ticket["available"] < qty:
        available = ticket["available"] if ticket else 0
        session["awaiting"] = "ticket_quantity"
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
