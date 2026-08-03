"""
Manual sanity check for the Dialogflow -> booking flow.
Requires DIALOGFLOW_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS to be set,
and a Dialogflow agent configured per plan.md's intent/entity contract.

Run directly: py test_dialogflow_booking.py
"""
import os
import sys
import uuid

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
sys.path.insert(0, os.path.dirname(_THIS_DIR))

from database import get_collection
from dialogflow_bot import handle_dialogflow_message


def run_turns(session_id, turns):
    for message in turns:
        response_text, intent, confidence = handle_dialogflow_message(session_id, message)
        print(f"> {message}")
        print(f"< [{intent}, confidence={confidence:.2f}] {response_text}\n")


def test_affirm_path():
    session_id = str(uuid.uuid4())
    run_turns(session_id, ["I want to buy tickets", "Concert A", "3", "yes"])

    bookings_col = get_collection("bookings")
    booking = bookings_col.find_one({"session_id": session_id})

    assert booking is not None, "No booking document was created."
    assert booking["event_name"] == "Concert A", f"Unexpected event_name: {booking['event_name']}"
    assert booking["ticket_quantity"] == 3, f"Unexpected ticket_quantity: {booking['ticket_quantity']}"

    print("PASS: affirm path recorded booking correctly ->", booking)


def test_deny_path():
    session_id = str(uuid.uuid4())
    run_turns(session_id, ["I want to buy tickets", "Concert A", "3", "no"])

    bookings_col = get_collection("bookings")
    booking = bookings_col.find_one({"session_id": session_id})

    assert booking is None, f"Booking document should not exist after deny, got: {booking}"

    print("PASS: deny path created no booking, as expected.")


if __name__ == "__main__":
    test_affirm_path()
    test_deny_path()
    print("\nALL TESTS PASSED")