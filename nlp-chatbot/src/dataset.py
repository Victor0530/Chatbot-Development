"""Loads intents.json and builds the (text, label) training pairs."""
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "intents.json"


def load_intents(path: Path = DATA_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_training_pairs(intents: dict) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    for intent in intents["intents"]:
        for pattern in intent["patterns"]:
            texts.append(pattern)
            labels.append(intent["tag"])
    return texts, labels


def build_response_map(intents: dict) -> dict[str, list[str]]:
    return {intent["tag"]: intent["responses"] for intent in intents["intents"]}
