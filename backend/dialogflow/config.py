import os
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(_ENV_PATH)

DIALOGFLOW_PROJECT_ID = os.getenv("DIALOGFLOW_PROJECT_ID", "")
