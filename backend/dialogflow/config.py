import os
from dotenv import load_dotenv

load_dotenv()

DIALOGFLOW_PROJECT_ID = os.getenv("DIALOGFLOW_PROJECT_ID", "")
