import os
from pathlib import Path
from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")

DIALOGFLOW_PROJECT_ID = os.getenv("DIALOGFLOW_PROJECT_ID", "")

# GOOGLE_APPLICATION_CREDENTIALS is read directly from os.environ by google-auth,
# which resolves relative paths against the current working directory rather than
# backend/. Rewrite it to an absolute path here so scripts work no matter where
# they're invoked from.
_credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if _credentials_path and not os.path.isabs(_credentials_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str((_BACKEND_DIR / _credentials_path).resolve())
