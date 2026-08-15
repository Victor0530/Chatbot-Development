import os
import sys
from datetime import datetime

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
sys.path.insert(0, os.path.dirname(_THIS_DIR))

from database import get_collection
from dialogflow_client import detect_intent, extract_slot_params, extract_query_params


def handle_dialogflow_message(session_id: str, message: str):
    """Returns (response_text, intent, confidence)."""
    try:
        query_result = detect_intent(session_id, message)
    except Exception as e:
        print(f"Dialogflow error: {e}")
        return "Sorry, something went wrong.", "dialogflow_error", 0.0

    intent = query_result.intent.display_name
    confidence = query_result.intent_detection_confidence
    response_text = query_result.fulfillment_text or "I understood you, but have no response."

    if intent == "affirm":
        params = extract_slot_params(query_result)
        event_name = params.get("event_name")
        quantity = params.get("ticket_quantity")
        if event_name and quantity:
            tickets_col = get_collection("tickets")
            ticket = tickets_col.find_one({"event": {"$regex": event_name, "$options": "i"}})
            if not ticket or ticket.get("available", 0) < quantity:
                available = ticket.get("available", 0) if ticket else 0
                response_text = f"Sorry, only {available} tickets left for {event_name}. Booking not confirmed."
            else:
                bookings_col = get_collection("bookings")
                bookings_col.insert_one({
                    "session_id": session_id,
                    "event_name": params["event_name"],
                    "ticket_quantity": quantity,
                    "timeframe": params["timeframe"],
                    "status": "confirmed",
                    "created_at": datetime.utcnow().isoformat()
                })
                tickets_col.update_one({"_id": ticket["_id"]}, {"$inc": {"available": -quantity}})
    elif intent.lower() == "query_events":
        query_params = extract_query_params(query_result)
        category = query_params.get("category")
        timeframe = query_params.get("timeframe")
        if timeframe:
            pass  # TODO: real date-range matching against the "date" field needs more logic later

        tickets_col = get_collection("tickets")
        matches = []
        for t in tickets_col.find():
            if t.get("available", 0) <= 0:
                continue
            if category and (t.get("category") or "").lower() != category.lower():
                continue
            matches.append(t)
        matches = matches[:5]

        if matches:
            lines = [
                f"- {t.get('event')} — {t.get('date')} @ {t.get('venue')} (RM{t.get('price')}, {t.get('available')} left)"
                for t in matches
            ]
            response_text = "Here are some events you might like:\n" + "\n".join(lines)
        else:
            response_text = "Sorry, I couldn't find any events matching that. Want to see everything we have?"

    return response_text, intent, confidence
