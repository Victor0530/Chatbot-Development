"""NLP preprocessing pipeline (Chapter 6: tokenization, stopword removal, lemmatization)."""
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
_stopwords = set(stopwords.words("english")) - {
    "when", "where", "how", "what", "why", "who", "which",
}
_punctuation = set(string.punctuation)


def preprocess(text: str) -> str:
    """Lowercase, tokenize, strip punctuation/stopwords, then lemmatize."""
    tokens = word_tokenize(text.lower())
    cleaned = [
        _lemmatizer.lemmatize(token)
        for token in tokens
        if token not in _punctuation and token not in _stopwords
    ]
    return " ".join(cleaned)
