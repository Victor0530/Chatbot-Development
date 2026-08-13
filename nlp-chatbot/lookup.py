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

_MONTH_NAMES = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_MONTH_DISPLAY = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Words that unambiguously mean "which event is most/least popular" on
# their own - safe to trust regardless of what else is in the message.
_STRONG_POPULARITY_WORDS = {"popular", "famous", "unfamous", "unpopular", "selling"}
# "sold"/"bought"/"purchased"/"booked" are weaker signals: they also show up
# in "which events have I already booked" (a personal-history question this
# bot doesn't support, not a popularity one), so they're only trusted absent
# a first-person pronoun - see _is_popularity_query.
_WEAK_POPULARITY_WORDS = {"sold", "bought", "purchased", "booked", "booking", "bookings"}
_FIRST_PERSON_WORDS = {"i", "my", "me", "mine"}
# Presence of any of these flips the answer from most- to least-popular
# (and, like the words above, is also enough on its own to signal a
# popularity query - "which event has the fewest bookings"). "most" itself
# isn't listed here - it's an NLTK stopword and gets stripped before
# classification anyway, so it can't be relied on as a signal, but its
# absence doesn't matter either: default to "most" whenever none of these
# fire.
_LEAST_POPULAR_WORDS = {"lowest", "fewest", "worst", "unpopular", "unfamous"}

# Mirrors booking.py's ESCAPE_CONFIDENCE_THRESHOLD - how sure the ML
# classifier has to be about a different intent before a message that
# didn't name a known event is treated as a topic change rather than just a
# bad answer to "which event?".
ESCAPE_CONFIDENCE_THRESHOLD = 0.5

LOOKUP_INTENTS = {"check_price", "event_schedule", "event_location"}

_ANSWER_BUILDERS = {
    "check_price": lambda t: f"{t['event']} costs RM{t['price']:.2f}, with {t['available']} seats left.",
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


def list_events(message: str = "") -> str:
    """Build a live list of bookable events from the tickets collection. If
    `message` narrows that down - a venue ("what events are at Grand
    Theater"), a month ("what's on in July"), or a popularity question
    ("what's the most popular event") - answer that instead of dumping the
    full list. The classifier routes all of these to list_events too, since
    bag-of-words can't tell "what events are available" apart from "what
    events are at X"/"in July"/"most popular"."""
    if message:
        venue_tickets = find_tickets_by_venue(message)
        if venue_tickets:
            return describe_events_at_venue(venue_tickets)

        month_tickets = find_tickets_by_month(message)
        if month_tickets is not None:
            return describe_events_in_month(message, month_tickets)

        popularity = popularity_answer(message)
        if popularity is not None:
            return popularity

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


def _matching_tickets_by_venue(db, text: str) -> list[dict]:
    """All tickets whose venue is referenced in `text`, matching the same way
    _matching_tickets does for event names against the *full* venue name
    ("Grand Theater"). Deliberately doesn't fall back to matching just the
    venue's first word the way _matching_tickets does for events (via its
    "Concert A - Pop Night" -> "Concert A" split) - venues have no such
    dash-delimited short form, and their first word alone ("city", "grand")
    is often just an ordinary English word, which turned plain sentences
    like "what events are happening in the city" into a false venue match."""
    text_lower = text.strip().lower()
    if len(text_lower) < 3:
        return []
    matches = []
    for t in db.tickets.find():
        venue_lower = t["venue"].lower()
        if _word_match(venue_lower, text_lower) or _word_match(text_lower, venue_lower):
            matches.append(t)
    return matches


def find_tickets_by_venue(message: str) -> list[dict]:
    """Tickets whose venue is named in `message`, e.g. "what events are at
    Grand Theater" - the reverse of the usual event-name lookup. Returns []
    if the database is unavailable or nothing matches."""
    db = _get_db()
    if db is None:
        return []
    try:
        return _matching_tickets_by_venue(db, message)
    except PyMongoError:
        return []


def describe_events_at_venue(tickets: list[dict]) -> str:
    """Format a find_tickets_by_venue() result for the user. Assumes
    `tickets` is non-empty - callers should fall back to their normal flow
    when find_tickets_by_venue() returns []. `tickets` can span more than
    one distinct venue if the message loosely matched several ("...at the
    grand city hall" matching both Grand Theater and City Center) - name
    them as ambiguous rather than mislabeling one venue's events under
    another's name."""
    venues = sorted({t["venue"] for t in tickets})
    if len(venues) > 1:
        return f"I found more than one matching venue: {', '.join(venues)}. Which one did you mean?"
    venue = venues[0]
    if len(tickets) == 1:
        return f"{tickets[0]['event']} is being held at {venue}."
    names = ", ".join(t["event"] for t in tickets)
    return f"The following events are at {venue}: {names}."


# "may" the month and "may" the modal verb ("may I...", "that may help")
# are the same token once lowercased, so a plain word match on "may" turns
# ordinary polite phrasing into a false month match. Only trust it when
# preceded by a preposition that actually signals a date ("in May",
# "during May") - the other month names/abbreviations don't collide with
# common words this way, so they don't need the same guard.
_AMBIGUOUS_MONTH_WORDS = {"may"}
_MONTH_CONTEXT_PREPOSITIONS = ("in", "during", "for", "on", "by")


def _find_month_in_message(text: str) -> Optional[int]:
    text_lower = text.lower()
    for name, num in _MONTH_NAMES.items():
        match = re.search(rf"\b{re.escape(name)}\b", text_lower)
        if not match:
            continue
        if name in _AMBIGUOUS_MONTH_WORDS:
            prefix = text_lower[:match.start()].rstrip()
            if not prefix.endswith(_MONTH_CONTEXT_PREPOSITIONS):
                continue
        return num
    return None


def _ticket_month(t: dict) -> Optional[int]:
    try:
        return int(t["date"].split("-")[1])
    except (KeyError, IndexError, ValueError):
        return None


def find_tickets_by_month(message: str) -> Optional[list[dict]]:
    """Tickets scheduled in the month named in `message` ("what's on in
    July"). Returns None if no month is named at all - distinct from an
    empty list, which means a month was named but nothing is scheduled
    then, so the caller should say so rather than falling back to the full
    event list."""
    month = _find_month_in_message(message)
    if month is None:
        return None
    db = _get_db()
    if db is None:
        return []
    try:
        return [t for t in db.tickets.find() if _ticket_month(t) == month]
    except PyMongoError:
        return []


def describe_events_in_month(message: str, tickets: list[dict]) -> str:
    """Format a find_tickets_by_month() result. `message` is re-scanned for
    the month name rather than threading the int through, since callers
    already have the original message on hand."""
    name = _MONTH_DISPLAY[_find_month_in_message(message)]
    if not tickets:
        return f"There are no events scheduled in {name}."
    names = ", ".join(t["event"] for t in tickets)
    return f"In {name}, we have: {names}."


def _has_least_signal(text_lower: str) -> bool:
    """Whether "least" appears as an actual "least popular" signal, not as
    part of the "at least" filler phrase ("can you at least list the
    events") - the far more common use of the word in this domain."""
    for match in re.finditer(r"\bleast\b", text_lower):
        if not text_lower[:match.start()].rstrip().endswith("at"):
            return True
    return False


def _is_popularity_query(text: str) -> bool:
    text_lower = text.lower()
    if any(_word_match(w, text_lower) for w in _STRONG_POPULARITY_WORDS):
        return True
    # "fewest"/"lowest"/"worst" (and a real "least") are unambiguous
    # popularity signals on their own, not just direction modifiers -
    # "which event has the fewest bookings" should trigger this even
    # without "popular"/"sold" also present.
    if any(_word_match(w, text_lower) for w in _LEAST_POPULAR_WORDS) or _has_least_signal(text_lower):
        return True
    if any(_word_match(w, text_lower) for w in _WEAK_POPULARITY_WORDS):
        # "booked"/"sold"/etc. alongside "I"/"my"/"me" ("which events have I
        # already booked") is almost always about the user's own booking
        # history, not the event's overall popularity.
        return not any(_word_match(w, text_lower) for w in _FIRST_PERSON_WORDS)
    return False


def _wants_least_popular(text: str) -> bool:
    text_lower = text.lower()
    return any(_word_match(w, text_lower) for w in _LEAST_POPULAR_WORDS) or _has_least_signal(text_lower)


def _event_popularity(db) -> list[tuple[str, int]]:
    """[(event_name, total_tickets_sold)] for every ticket in the catalog,
    including events with zero bookings so they're valid "least popular"
    candidates - db.bookings only has rows for events that sold at least
    one ticket."""
    sold: dict[str, int] = {}
    for doc in db.bookings.aggregate([
        {"$match": {"status": "booked"}},
        {"$group": {"_id": "$event", "total": {"$sum": "$quantity"}}},
    ]):
        sold[doc["_id"]] = doc["total"]
    return [(t["event"], sold.get(t["event"], 0)) for t in db.tickets.find()]


def popularity_answer(message: str) -> Optional[str]:
    """Answer a "most/least popular event" style question, or None if
    `message` isn't one - see _is_popularity_query."""
    if not _is_popularity_query(message):
        return None
    db = _get_db()
    if db is None:
        return "Sorry, the event list is temporarily unavailable. Please try again in a moment."
    try:
        stats = _event_popularity(db)
    except PyMongoError:
        return "Sorry, I couldn't reach the database. Please try again in a moment."
    if not stats:
        return "There are no events open for booking right now."

    least = _wants_least_popular(message)
    event, total = min(stats, key=lambda s: s[1]) if least else max(stats, key=lambda s: s[1])
    direction = "least" if least else "most"
    if total == 0:
        return f"{event} hasn't sold any tickets yet, making it the least popular event right now."
    return f"{event} is the {direction} popular event right now, with {total} ticket(s) sold."


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
