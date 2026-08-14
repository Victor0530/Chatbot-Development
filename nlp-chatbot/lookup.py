"""Two-turn lookups for check_price / event_schedule / event_location: ask
for the event name, then answer from the tickets collection.

Mirrors booking.py's session pattern, but simpler - there's only ever one
pending question (the event name), so a session is just the intent tag
waiting on an answer rather than a multi-state machine.
"""
import calendar
import datetime
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
    Theater"), a category ("what music events do you have"), a price
    threshold ("events under RM100"), a specific date ("what's on June 15"),
    a relative timeframe ("what's happening this weekend"), a month ("what's
    on in July"), or a popularity question ("what's the most popular
    event") - answer that instead of dumping the full list. The classifier
    routes all of these to list_events too, since bag-of-words can't tell
    "what events are available" apart from "what events are at X"/"under
    RM100"/"in July"/"most popular"."""
    if message:
        venue_tickets = find_tickets_by_venue(message)
        if venue_tickets:
            return describe_events_at_venue(venue_tickets)

        category_tickets = find_tickets_by_category(message)
        if category_tickets is not None:
            return describe_events_in_category(message, category_tickets)

        price_tickets = find_tickets_by_price(message)
        if price_tickets is not None:
            return describe_events_by_price(message, price_tickets)

        date_tickets = find_tickets_by_date(message)
        if date_tickets is not None:
            return describe_events_on_date(message, date_tickets)

        timeframe_tickets = find_tickets_by_timeframe(message)
        if timeframe_tickets is not None:
            return describe_events_in_timeframe(message, timeframe_tickets)

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
    short reply ("Concert A", "Pop Night", "broadway") or embedded in a full
    sentence ("what's the price of Broadway Musical", "what's the price for
    Pop Night?"). Matches in both directions so both styles work, but only
    on whole-word/phrase boundaries. Checks the part before *and* after the
    " - " separator on its own ("Concert A" / "Pop Night" for "Concert A -
    Pop Night") - matching only the text-within-event direction for the
    full name would otherwise miss the subtitle half whenever it's embedded
    in a longer sentence rather than sent standalone (a standalone "Pop
    Night" happens to also satisfy the reverse, text-contained-in-event
    check, which is why only the prefix half seemed to need this). Messages
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
        prefix_lower, _, suffix_lower = t["event"].lower().partition(" - ")
        if (
            _word_match(prefix_lower, text_lower)
            or (suffix_lower and _word_match(suffix_lower, text_lower))
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


_CATEGORIES = ("music", "sports", "theater", "comedy")


def _find_category_in_message(text: str) -> Optional[str]:
    text_lower = text.lower()
    for category in _CATEGORIES:
        if _word_match(category, text_lower):
            return category
    if _word_match("theatre", text_lower):
        return "theater"
    return None


def find_tickets_by_category(message: str) -> Optional[list[dict]]:
    """Tickets whose category is named in `message` ("what music events do
    you have"). Returns None if no category is named at all - distinct from
    an empty list, which means a category was named but nothing is
    scheduled in it."""
    category = _find_category_in_message(message)
    if category is None:
        return None
    db = _get_db()
    if db is None:
        return []
    try:
        return [t for t in db.tickets.find() if t.get("category") == category]
    except PyMongoError:
        return []


def describe_events_in_category(message: str, tickets: list[dict]) -> str:
    """Format a find_tickets_by_category() result. `message` is re-scanned
    for the category name rather than threading it through, same as
    describe_events_in_month()."""
    category = _find_category_in_message(message)
    if not tickets:
        return f"There are no {category} events scheduled right now."
    names = ", ".join(t["event"] for t in tickets)
    return f"Here are the {category} events: {names}."


# Only "RM<amount>" is recognized (matches the standardized entity's expected
# format, e.g. "RM50") - a bare number is too easy to confuse with a ticket
# quantity or some other digit in the sentence.
_PRICE_RE = re.compile(r"\brm\s?(\d+(?:\.\d{1,2})?)\b")
_UNDER_WORDS = ("under", "below", "less than", "cheaper than", "no more than", "at most", "within", "up to")
_OVER_WORDS = ("over", "above", "more than", "at least", "starting from")


def _find_price_in_message(text: str) -> Optional[float]:
    match = _PRICE_RE.search(text.lower())
    return float(match.group(1)) if match else None


def _price_direction(text: str) -> Optional[str]:
    text_lower = text.lower()
    if any(w in text_lower for w in _UNDER_WORDS):
        return "under"
    if any(w in text_lower for w in _OVER_WORDS):
        return "over"
    return None


def find_tickets_by_price(message: str) -> Optional[list[dict]]:
    """Tickets priced under/over the RM amount named in `message` ("events
    under RM100"). Requires both a price and a comparison direction word -
    an amount alone is too ambiguous to guess a direction for. Returns None
    if either is missing, distinct from an empty list (a threshold was
    given but nothing qualifies)."""
    price = _find_price_in_message(message)
    direction = _price_direction(message)
    if price is None or direction is None:
        return None
    db = _get_db()
    if db is None:
        return []
    try:
        tickets = list(db.tickets.find())
    except PyMongoError:
        return []
    if direction == "under":
        return [t for t in tickets if t["price"] <= price]
    return [t for t in tickets if t["price"] >= price]


def describe_events_by_price(message: str, tickets: list[dict]) -> str:
    price = _find_price_in_message(message)
    direction = _price_direction(message)
    if not tickets:
        return f"There are no events priced {direction} RM{price:.2f}."
    names = ", ".join(f"{t['event']} (RM{t['price']:.2f})" for t in tickets)
    return f"Events priced {direction} RM{price:.2f}: {names}."


# "may" the month and "may" the modal verb ("may I...", "that may help")
# are the same token once lowercased, so a plain word match on "may" turns
# ordinary polite phrasing into a false month match. Only trust it when
# preceded by a preposition that actually signals a date ("in May",
# "during May") - the other month names/abbreviations don't collide with
# common words this way, so they don't need the same guard.
_AMBIGUOUS_MONTH_WORDS = {"may"}
_MONTH_CONTEXT_PREPOSITIONS = ("in", "during", "for", "on", "by")


def _find_month_match(text_lower: str):
    """The regex Match for the month name found in `text_lower`, plus its
    numeric value - exposed (not just the int) so _parse_specific_date can
    anchor its day search to where the month was actually found, rather
    than scanning the whole message."""
    for name, num in _MONTH_NAMES.items():
        match = re.search(rf"\b{re.escape(name)}\b", text_lower)
        if not match:
            continue
        if name in _AMBIGUOUS_MONTH_WORDS:
            prefix = text_lower[:match.start()].rstrip()
            if not prefix.endswith(_MONTH_CONTEXT_PREPOSITIONS):
                continue
        return match, num
    return None, None


def _find_month_in_message(text: str) -> Optional[int]:
    _, num = _find_month_match(text.lower())
    return num


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


_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DAY_RE = re.compile(r"\b([1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b")


def _parse_specific_date(text: str) -> Optional[tuple[Optional[int], int, int]]:
    """(year, month, day) named in `text`, either ISO ("2026-06-15") or
    "<Month> <day>" ("June 15"), or None if no specific date is named.
    `year` is None for the "<Month> <day>" form - callers then match on
    month/day alone, regardless of year, since the dataset's events don't
    all necessarily share one year."""
    text_lower = text.lower()
    iso = _ISO_DATE_RE.search(text_lower)
    if iso:
        year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return year, month, day
    month_match, month = _find_month_match(text_lower)
    if month is None:
        return None
    # Only look for the day right around the month name, not anywhere in the
    # message - an earlier unrelated number (e.g. a ticket quantity) would
    # otherwise be misread as the day.
    window_start = max(0, month_match.start() - 15)
    window_end = min(len(text_lower), month_match.end() + 15)
    day_match = _DAY_RE.search(text_lower[window_start:window_end])
    if not day_match:
        return None
    return None, month, int(day_match.group(1))


def find_tickets_by_date(message: str) -> Optional[list[dict]]:
    """Tickets on the specific calendar date named in `message` - distinct
    from find_tickets_by_month/find_tickets_by_timeframe, which match a
    whole month or relative range rather than one exact day. Returns None
    if no specific date is named at all."""
    parsed = _parse_specific_date(message)
    if parsed is None:
        return None
    year, month, day = parsed
    db = _get_db()
    if db is None:
        return []
    try:
        tickets = list(db.tickets.find())
    except PyMongoError:
        return []
    matches = []
    for t in tickets:
        try:
            t_year, t_month, t_day = (int(p) for p in t["date"].split("-"))
        except (KeyError, ValueError):
            continue
        if t_month == month and t_day == day and (year is None or year == t_year):
            matches.append(t)
    return matches


def describe_events_on_date(message: str, tickets: list[dict]) -> str:
    parsed = _parse_specific_date(message)
    label = message.strip()
    if parsed:
        _, month, day = parsed
        label = f"{_MONTH_DISPLAY[month]} {day}"
    if not tickets:
        return f"There are no events scheduled on {label}."
    names = ", ".join(t["event"] for t in tickets)
    return f"On {label}, we have: {names}."


def _timeframe_range(text: str) -> Optional[tuple[datetime.date, datetime.date, str]]:
    """(start_date, end_date, label) for the relative timeframe phrase named
    in `text` ("tomorrow", "this weekend", "next month"...), computed from
    the real current date - unlike find_tickets_by_month, which matches a
    literal month name regardless of year. Checked most-specific phrase
    first: "this weekend" is a plain substring of "this week" once "weekend"
    is un-split ("this week" + "end"), so it must be checked before the
    "this week" branch or every weekend question would be misread as a
    whole-week one."""
    text_lower = text.lower()
    today = datetime.date.today()
    if _word_match("tomorrow", text_lower):
        d = today + datetime.timedelta(days=1)
        return d, d, "tomorrow"
    if "this weekend" in text_lower:
        days_to_sat = (5 - today.weekday()) % 7
        sat = today + datetime.timedelta(days=days_to_sat)
        sun = sat + datetime.timedelta(days=1)
        return sat, sun, "this weekend"
    if "next week" in text_lower:
        start = today + datetime.timedelta(days=7 - today.weekday())
        end = start + datetime.timedelta(days=6)
        return start, end, "next week"
    if "this week" in text_lower:
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)
        return start, end, "this week"
    if "next month" in text_lower:
        year, month = today.year, today.month + 1
        if month > 12:
            year, month = year + 1, 1
        end_day = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, 1), datetime.date(year, month, end_day), "next month"
    if "this month" in text_lower:
        end_day = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=end_day), "this month"
    if _word_match("today", text_lower):
        return today, today, "today"
    return None


def find_tickets_by_timeframe(message: str) -> Optional[list[dict]]:
    """Tickets falling within the relative date range named in `message`
    ("what's on tomorrow", "any events this weekend"). Returns None if no
    relative timeframe phrase is named at all."""
    result = _timeframe_range(message)
    if result is None:
        return None
    start, end, _label = result
    db = _get_db()
    if db is None:
        return []
    try:
        tickets = list(db.tickets.find())
    except PyMongoError:
        return []
    matches = []
    for t in tickets:
        try:
            t_date = datetime.date.fromisoformat(t["date"])
        except (KeyError, ValueError):
            continue
        if start <= t_date <= end:
            matches.append(t)
    return matches


def describe_events_in_timeframe(message: str, tickets: list[dict]) -> str:
    result = _timeframe_range(message)
    label = result[2] if result else "that time"
    if not tickets:
        return f"There are no events scheduled {label}."
    names = ", ".join(t["event"] for t in tickets)
    return f"Events {label}: {names}."


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
