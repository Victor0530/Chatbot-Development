"""Loads a trained classifier and turns predictions into responses.

Low-confidence predictions fall back to a clarification response instead of a
guessed intent — a simple certainty-threshold rule inspired by the Chapter 12
certainty-factor idea (reject any conclusion below a belief threshold).
"""
import difflib
import random
from pathlib import Path

import joblib

from src.dataset import build_response_map, load_intents
from src.preprocessing import preprocess

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
CONFIDENCE_THRESHOLD = 0.2
FALLBACK_RESPONSES = [
    "Sorry, I didn't quite understand that. Could you rephrase?",
    "I'm not sure I follow - could you tell me more about what you need (booking, price, schedule, etc.)?",
]

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
}


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
        too many equally-close neighbors to correct safely) and skips
        anything already in vocabulary."""
        corrected = []
        for token in cleaned.split():
            if token in self._vocab or len(token) < 4:
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
        return self.predict_intent(message)

    def get_response(self, message: str) -> str:
        tag, confidence = self.resolve_intent(message)
        if tag is None or confidence < CONFIDENCE_THRESHOLD:
            return random.choice(FALLBACK_RESPONSES)
        return random.choice(self.response_map[tag])
