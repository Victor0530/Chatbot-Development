"""Loads a trained classifier and turns predictions into responses.

Low-confidence predictions fall back to a clarification response instead of a
guessed intent — a simple certainty-threshold rule inspired by the Chapter 12
certainty-factor idea (reject any conclusion below a belief threshold).
"""
import difflib
import random
import re
from pathlib import Path

import joblib
from nltk import pos_tag, word_tokenize

from src.dataset import build_response_map, load_intents
from src.preprocessing import preprocess

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
CONFIDENCE_THRESHOLD = 0.2
FALLBACK_RESPONSES = [
    "Sorry, I didn't quite understand that. Could you rephrase?",
    "I'm not sure I follow - could you tell me more about what you need (booking, price, schedule, etc.)?",
]

# Bar a message's remainder (after stripping a leading "Hi,"/"Hello there,")
# must clear before that remainder's intent overrides a plain "greeting"
# read of the full message. Deliberately higher than CONFIDENCE_THRESHOLD
# (0.2, "trust the classifier's best guess over no guess at all"): several
# greeting training patterns are themselves greeting-plus-vague-followup
# ("hi, i have a question about an event"), so a weak/ambiguous guess on the
# remainder shouldn't override that - only a confident, clearly-different
# intent should. Same reasoning as booking.py's ESCAPE_CONFIDENCE_THRESHOLD.
GREETING_OVERRIDE_CONFIDENCE_THRESHOLD = 0.5

# Matches a leading greeting opener so it can be stripped off and the rest
# of the message classified on its own merits - see resolve_intent(). Kept
# to the greeting intent's own single-word/short openers (data/intents.json)
# rather than its longer "greeting + vague followup" patterns, since those
# longer ones are exactly the case that should keep resolving as "greeting".
_GREETING_PREFIX_RE = re.compile(
    r"^(hi+|hello|hey+|hiya|howdy|greetings?|good\s+(morning|afternoon|evening))\b[\s,!.]*",
    re.IGNORECASE,
)


def strip_greeting_prefix(message: str) -> str | None:
    """The remainder of `message` after a leading greeting phrase ("Hi,",
    "Hello there -"), or None if there's no such prefix or nothing
    meaningful follows it (a bare "Hello" should still resolve as its own
    greeting intent, not an override with nothing to override to)."""
    match = _GREETING_PREFIX_RE.match(message.strip())
    if not match:
        return None
    remainder = message[match.end():].strip(" ,.-!?")
    return remainder or None

# Chapter 11 (IF-THEN rule-based reasoning): fixed exact-match overrides for
# short, low-vocabulary phrasings that the classifier keeps getting wrong even
# after adding more training patterns for them. These clean down to just one or two
# rare tokens, which TF-IDF has almost no signal to separate from other short
# interjections (confirmed via cross-validation — "howdy"/"yo"/"gotta go" etc.
# stayed misclassified across two rounds of pattern expansion). Matching the
# known phrasing directly, before the ML step, sidesteps that limitation.
RULE_OVERRIDES = {
    # "how/what can you do" clean down to all-stopword empty vectors.
    "what can you do": "bot_capabilities",
    "how can you do": "bot_capabilities",
    "what do you do": "bot_capabilities",
    "how can you help me": "bot_capabilities",
    "how can you help": "bot_capabilities",
    "what can you help me with": "bot_capabilities",
    "what can you assist with": "bot_capabilities",
    "how can you assist me": "bot_capabilities",
    # short greeting interjections the classifier keeps confusing with goodbye.
    "howdy": "greeting",
    "yo": "greeting",
    "hiya": "greeting",
    "greetings": "greeting",
    "nice to meet you": "greeting",
    "what's up": "greeting",
    # short farewells the classifier keeps confusing with other intents.
    "gotta go": "goodbye",
    "i have to go": "goodbye",
    "no more questions": "goodbye",
    "i'm signing off now": "goodbye",
    # clean down to all-stopword empty vectors, same as the bot_capabilities
    # phrases above - unlearnable by the classifier no matter how the rest of
    # the training set is worded.
    "that's all": "goodbye",
    "that will be all": "goodbye",
    # cleans down to just "what" - indistinguishable from bot_capabilities'
    # "what can you do" without this override.
    "what's on": "list_events",
    # cleans down to just "help", a token shared with several bot_capabilities
    # patterns ("how can you help me", "what can you help me with") - with no
    # other context to disambiguate, the classifier leans bot_capabilities.
    "that helps": "thanks",
    # "question" also appears in goodbye's "no more questions" pattern, close
    # enough in this small a training set to outweigh "thanks" itself.
    "thanks, that answers my question": "thanks",
    # cleans down to "how secure seat" - "how" is heavily shared with
    # bot_capabilities patterns ("how can you help me", "how do you work"),
    # which outweighs "secure"/"seat" despite them being the real signal.
    "how do i secure my seat": "book_ticket",
}

# "is the event this weekend" (event_schedule) and "are there any events
# this weekend" (list_events) both reduce to the identical bag-of-words
# ("event weekend") after preprocessing strips "is"/"the"/"any"/"this" as
# stopwords - no amount of training data can teach a linear classifier to
# separate two identical feature vectors. The distinguishing signal is
# syntactic (a definite/demonstrative determiner directly on a singular
# noun, "the event", vs. an indefinite/plural phrasing, "any events"), which
# only POS tags still carry once the raw words are gone. Scoped to the
# specific words that actually collide with list_events' timeframe patterns
# (see lookup.py's find_tickets_by_timeframe) - "when is the event" doesn't
# need this, the classifier already gets that right on its own.
_DEFINITE_DETERMINERS = {"the", "this", "that"}
# "this weekend"/"this month" are themselves a determiner directly on a
# singular noun ("this" + NN "weekend") - structurally indistinguishable
# from "the event" by POS tag alone. Excluded here so the timeframe word
# itself never counts as the "specific event" being referred to; only a
# *different* singular noun after the determiner does.
_TIME_NOUNS = {"weekend", "today", "tomorrow", "week", "month"}
_SCHEDULE_COLLISION_WORDS_RE = re.compile(
    r"\b(weekend|today|tomorrow|this week|next week|this month|next month)\b"
)
# Guards against the rarer sentence that also names "the event" + one of the
# words above but is actually asking about location or price, not timing.
_COMPETING_SIGNAL_WORDS_RE = re.compile(
    r"\b(where|venue|located|held|price|cost|rm|expensive|cheap)\b"
)


def _refers_to_a_specific_event(normalized: str) -> bool:
    """Whether `normalized` has a definite/demonstrative determiner directly
    in front of a singular noun that isn't itself a timeframe word ("the
    event", "this show", but not "this weekend") - see the RULE_OVERRIDES
    comment above this for why."""
    tags = pos_tag(word_tokenize(normalized))
    return any(
        word in _DEFINITE_DETERMINERS and next_tag == "NN" and next_word not in _TIME_NOUNS
        for (word, _tag), (next_word, next_tag) in zip(tags, tags[1:])
    )


class ChatBot:
    def __init__(self, classifier_name: str = "svm"):
        self.vectorizer = joblib.load(MODELS_DIR / "vectorizer.joblib")
        self.label_encoder = joblib.load(MODELS_DIR / "label_encoder.joblib")
        self.model = joblib.load(MODELS_DIR / f"{classifier_name}.joblib")
        self.response_map = build_response_map(load_intents())
        self._vocab = set(self.vectorizer.vocabulary_)

    def _correct_typos(self, cleaned: str) -> str:
        """Nudge misspelled words ("prive") toward the closest word the
        vectorizer actually knows ("price"), so a typo doesn't just vanish
        as an out-of-vocabulary token and leave the classifier guessing off
        whatever's left. Only touches tokens of 4+ chars (short words have
        too many equally-close neighbors to correct safely), skips anything
        already in vocabulary, and skips purely numeric tokens - digit
        strings have no real "spelling" to correct, and fuzzy-matching them
        would only ever hit other digit strings that happen to share several
        characters (e.g. "123456" ~ "1234", the latter pulled into the
        vocabulary from a single "cancel booking number 1234" training
        example), misattributing arbitrary numbers to whatever intent that
        example belonged to."""
        corrected = []
        for token in cleaned.split():
            if token in self._vocab or len(token) < 4 or token.isdigit():
                corrected.append(token)
                continue
            match = difflib.get_close_matches(token, self._vocab, n=1, cutoff=0.8)
            corrected.append(match[0] if match else token)
        return " ".join(corrected)

    def predict_intent(self, message: str) -> tuple[str | None, float]:
        cleaned = self._correct_typos(preprocess(message))
        features = self.vectorizer.transform([cleaned])
        if features.nnz == 0:
            # No recognized vocabulary at all (empty after cleaning, or fully
            # out-of-vocabulary) - no evidence for the classifier to reason from, so
            # don't trust its argmax; treat it the same as "below threshold".
            return None, 0.0
        probabilities = self.model.predict_proba(features)[0]
        best_index = probabilities.argmax()
        tag = self.label_encoder.inverse_transform([best_index])[0]
        return tag, probabilities[best_index]

    def resolve_intent(self, message: str) -> tuple[str | None, float]:
        """Like predict_intent, but checks the exact-match rule overrides
        first. Callers that branch on the intent (api.py's session routing)
        must use this rather than predict_intent directly, or they'll act on
        a different tag than the one get_response actually replied with."""
        normalized = message.lower().strip().strip("?!.")
        if normalized in RULE_OVERRIDES:
            return RULE_OVERRIDES[normalized], 1.0
        if (
            _SCHEDULE_COLLISION_WORDS_RE.search(normalized)
            and not _COMPETING_SIGNAL_WORDS_RE.search(normalized)
            and _refers_to_a_specific_event(normalized)
        ):
            return "event_schedule", 1.0

        remainder = strip_greeting_prefix(message)
        if remainder is not None:
            tag, confidence = self.resolve_intent(remainder)
            if (
                tag is not None
                and tag != "greeting"
                and confidence >= GREETING_OVERRIDE_CONFIDENCE_THRESHOLD
            ):
                return tag, confidence

        return self.predict_intent(message)

    def get_response(self, message: str) -> str:
        tag, confidence = self.resolve_intent(message)
        if tag is None or confidence < CONFIDENCE_THRESHOLD:
            return random.choice(FALLBACK_RESPONSES)
        return random.choice(self.response_map[tag])
