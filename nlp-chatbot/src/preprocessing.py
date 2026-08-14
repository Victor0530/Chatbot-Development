"""NLP preprocessing pipeline (Chapter 6: tokenization, stopword removal, lemmatization)."""
import re
import string

import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

_REQUIRED_NLTK_DATA = [
    ("tokenizers/punkt", "punkt"),
    ("tokenizers/punkt_tab", "punkt_tab"),
    ("corpora/stopwords", "stopwords"),
    ("corpora/wordnet", "wordnet"),
    ("corpora/omw-1.4", "omw-1.4"),
    # POS tagger - used by chatbot.py's resolve_intent() to tell a definite
    # singular reference ("the event") apart from an indefinite/plural one
    # ("any events"), a distinction the TF-IDF bag-of-words can't see because
    # "the"/"any"/"this" are stripped as stopwords before vectorizing.
    ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
]


def ensure_nltk_data():
    for path, package in _REQUIRED_NLTK_DATA:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(package, quiet=True)


ensure_nltk_data()

_lemmatizer = WordNetLemmatizer()
# NLTK's default stopword list includes wh-question words ("when", "where", "how",
# "what", "why", "who", "which"). For intent classification, these are exactly the
# signal that distinguishes e.g. "when is the event" (schedule) from "where is the
# event" (location) — stripping them collapses both down to just "event". Keep them.
#
# Same reasoning for "on"/"up"/"all": stripping them collapsed "what's on" and
# "what's up" down to the identical bag-of-words "what" (confirmed via
# cross-validation - both then had to compete with bot_capabilities' own "what"-only
# patterns for the same single-token vector), and "that's all"/"that will be all"
# down to nothing at all (every other token in both is itself a stopword). Keeping
# these three restores the signal without a measurable cost elsewhere: 5-fold CV
# accuracy/f1_macro both improved (0.901/0.897 -> 0.920/0.915) rather than dropping.
_stopwords = set(stopwords.words("english")) - {
    "when", "where", "how", "what", "why", "who", "which",
    "on", "up", "all",
}
_punctuation = set(string.punctuation)

# word_tokenize splits contractions into the stem plus a bare clitic
# ("that's" -> "that", "'s"; "i'm" -> "i", "'m"). That clitic isn't real
# vocabulary - it's neither punctuation nor in the stopword list - so it
# survives as noise while the word it stood for (is/am/will/not...) is lost.
# Expanding contractions before tokenizing avoids that: the expansion is
# almost always a stopword itself, so it gets filtered out below the same as
# if the contraction had never been there.
_CONTRACTIONS = [
    (re.compile(r"\bwon't\b"), "will not"),
    (re.compile(r"\bcan't\b"), "cannot"),
    (re.compile(r"n't\b"), " not"),
    (re.compile(r"'re\b"), " are"),
    (re.compile(r"'ve\b"), " have"),
    (re.compile(r"'ll\b"), " will"),
    (re.compile(r"'d\b"), " would"),
    (re.compile(r"'m\b"), " am"),
    (re.compile(r"'s\b"), " is"),
]


def _expand_contractions(text: str) -> str:
    for pattern, expansion in _CONTRACTIONS:
        text = pattern.sub(expansion, text)
    return text


def preprocess(text: str) -> str:
    """Lowercase, expand contractions, tokenize, strip punctuation/stopwords, then lemmatize."""
    tokens = word_tokenize(_expand_contractions(text.lower()))
    cleaned = [
        _lemmatizer.lemmatize(token)
        for token in tokens
        if token not in _punctuation and token not in _stopwords
    ]
    return " ".join(cleaned)
