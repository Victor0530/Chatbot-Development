import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google.cloud import dialogflow
from google.protobuf.json_format import MessageToDict

from config import DIALOGFLOW_PROJECT_ID

_session_client = None


def _get_client():
    global _session_client
    if _session_client is None:
        _session_client = dialogflow.SessionsClient()
    return _session_client


def detect_intent(session_id: str, text: str, language_code: str = "en"):
    if not DIALOGFLOW_PROJECT_ID:
        raise RuntimeError("DIALOGFLOW_PROJECT_ID is not set.")
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not set.")

    client = _get_client()
    session = client.session_path(DIALOGFLOW_PROJECT_ID, session_id)
    text_input = dialogflow.TextInput(text=text, language_code=language_code)
    query_input = dialogflow.QueryInput(text=text_input)
    response = client.detect_intent(request={"session": session, "query_input": query_input})
    return response.query_result


def _normalize_value(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if value in (None, "", []):
        return None
    return value


def extract_slot_params(query_result) -> dict:
    params = {"event_name": None, "ticket_quantity": None, "timeframe": None}

    for ctx in query_result.output_contexts:
        ctx_dict = MessageToDict(ctx._pb)
        ctx_params = ctx_dict.get("parameters", {})
        if "event_name" not in ctx_params:
            continue
        for key in params:
            params[key] = _normalize_value(ctx_params.get(key))
        break

    return params


def extract_query_params(query_result) -> dict:
    result_dict = MessageToDict(query_result._pb)
    params_dict = result_dict.get("parameters", {})
    return {
        "category": _normalize_value(params_dict.get("category")),
        "timeframe": _normalize_value(params_dict.get("timeframe")),
    }
