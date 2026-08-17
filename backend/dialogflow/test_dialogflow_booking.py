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
        print(f"< [{intent}, confidence={confidence:.2f}] {response_text}")


def get_booking(session_id):
    return get_collection("bookings").find_one({"session_id": session_id})


def test_normal_booking():
    session_id = str(uuid.uuid4())
    print("\n=== test_normal_booking ===")
    run_turns(session_id, ["I want to book tickets", "Concert A", "3", "yes"])

    booking = get_booking(session_id)
    assert booking is not None, "No booking document was created."
    assert booking["event_name"] == "Concert A - Pop Night", f"Unexpected event_name: {booking.get('event_name')}"
    assert booking["ticket_quantity"] == 3, f"Unexpected ticket_quantity: {booking.get('ticket_quantity')}"
    assert booking["status"] == "confirmed", f"Unexpected status: {booking.get('status')}"

    print("PASS: normal booking flow ->", booking)


def test_deny_path():
    session_id = str(uuid.uuid4())
    print("\n=== test_deny_path ===")
    run_turns(session_id, ["I want to book tickets", "Concert A", "3", "no"])

    booking = get_booking(session_id)
    assert booking is None, f"Booking document should not exist after deny, got: {booking}"

    print("PASS: deny path created no booking, as expected.")


def test_change_event_at_confirm():
    session_id = str(uuid.uuid4())
    print("\n=== test_change_event_at_confirm ===")
    run_turns(session_id, ["I want to book tickets", "Concert A", "3", "change event", "Rock Fest", "yes"])

    booking = get_booking(session_id)
    assert booking is not None, "No booking document was created."
    assert booking["event_name"] == "Concert B - Rock Fest", f"Unexpected event_name: {booking.get('event_name')}"
    assert booking["ticket_quantity"] == 3, f"Unexpected ticket_quantity: {booking.get('ticket_quantity')}"

    print("PASS: change_event at confirm stage ->", booking)


def test_change_event_at_quantity():
    session_id = str(uuid.uuid4())
    print("\n=== test_change_event_at_quantity ===")
    run_turns(session_id, ["I want to book tickets", "Concert A", "change event", "Rock Fest", "3", "yes"])

    booking = get_booking(session_id)
    assert booking is not None, "No booking document was created."
    assert booking["event_name"] == "Concert B - Rock Fest", f"Unexpected event_name: {booking.get('event_name')}"
    assert booking["ticket_quantity"] == 3, f"Unexpected ticket_quantity: {booking.get('ticket_quantity')}"

    print("PASS: change_event at quantity stage ->", booking)


def test_cancel_booking():
    session_id = str(uuid.uuid4())
    print("\n=== test_cancel_booking ===")
    run_turns(session_id, ["I want to book tickets", "Concert A", "3", "cancel", "yes"])

    booking = get_booking(session_id)
    assert booking is None, f"Booking document should not exist after cancel, got: {booking}"

    print("PASS: cancel_booking flow created no booking, as expected.")


ALL_TESTS = [
    test_normal_booking,
    test_deny_path,
    test_change_event_at_confirm,
    test_change_event_at_quantity,
    test_cancel_booking,
]


if __name__ == "__main__":
    results = []
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            results.append((test_fn.__name__, "PASS", None))
        except AssertionError as e:
            print(f"FAIL: {test_fn.__name__} -> {e}")
            results.append((test_fn.__name__, "FAIL", str(e)))
        except Exception as e:
            print(f"ERROR: {test_fn.__name__} -> {e}")
            results.append((test_fn.__name__, "ERROR", str(e)))

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for name, status, detail in results:
        line = f"{status:5} {name}"
        if detail:
            line += f" -- {detail}"
        print(line)

    if any(status != "PASS" for _, status, _ in results):
        sys.exit(1)
