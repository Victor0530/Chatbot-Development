"""Trains and evaluates the SVM intent classifier on data/intents.json.

A calibrated linear SVM was chosen over the originally-tried MLPClassifier
(ANN) after comparing accuracy/F1 on this dataset: with only ~275 training
patterns across 12 intents, the linear SVM generalizes better than the ANN
(higher cross-validated F1-macro, lower variance across folds). It's wrapped
in CalibratedClassifierCV because LinearSVC has no predict_proba, which
chatbot.py's confidence-threshold fallback logic needs.

Usage:
    python train.py
"""
from pathlib import Path

import joblib
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC

from src.dataset import build_training_pairs, load_intents
from src.preprocessing import preprocess

MODELS_DIR = Path(__file__).resolve().parent / "models"


def main():
    intents = load_intents()
    texts, labels = build_training_pairs(intents)
    cleaned_texts = [preprocess(t) for t in texts]

    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(labels)

    vectorizer = TfidfVectorizer()
    X = vectorizer.fit_transform(cleaned_texts)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(vectorizer, MODELS_DIR / "vectorizer.joblib")
    joblib.dump(label_encoder, MODELS_DIR / "label_encoder.joblib")

    def build_model():
        return CalibratedClassifierCV(LinearSVC(), ensemble=False)

    model = build_model()
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, average="macro", zero_division=0)
    recall = recall_score(y_test, y_pred, average="macro", zero_division=0)
    f1 = f1_score(y_test, y_pred, average="macro", zero_division=0)

    joblib.dump(model, MODELS_DIR / "svm.joblib")

    print("\n=== svm ===")
    print(classification_report(y_test, y_pred, target_names=label_encoder.classes_, zero_division=0))

    print("Confusion matrix (rows=true, cols=predicted):")
    print(label_encoder.classes_)
    print(confusion_matrix(y_test, y_pred))

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_acc = cross_val_score(build_model(), X, y, cv=cv, scoring="accuracy")
    cv_f1 = cross_val_score(build_model(), X, y, cv=cv, scoring="f1_macro")
    print(f"5-fold CV accuracy: {cv_acc.mean():.3f} (+/- {cv_acc.std():.3f})")
    print(f"5-fold CV f1_macro: {cv_f1.mean():.3f} (+/- {cv_f1.std():.3f})")

    print(f"\naccuracy={acc:.3f} precision={precision:.3f} recall={recall:.3f} f1={f1:.3f}")


if __name__ == "__main__":
    main()
