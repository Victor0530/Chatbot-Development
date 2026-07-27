import os
from pymongo import MongoClient
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from rasa_sdk.forms import FormValidationAction
from typing import Any, Text, Dict, List

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable is not set")
DB_NAME = os.getenv("DB_NAME", "chatbot_ticketing")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

class ActionStartBooking(Action):
    def name(self) -> Text:
        return "action_start_booking"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        return [SlotSet("event_name", None), SlotSet("ticket_quantity", None)]

class ActionSearchTickets(Action):
    def name(self) -> Text:
        return "action_search_tickets"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        event_name = tracker.get_slot("event_name")
        
        if not event_name:
            # If no event name in slot, list all available events
            tickets = list(db.tickets.find())
            if tickets:
                event_list = ", ".join([t['event'] for t in tickets])
                dispatcher.utter_message(text=f"Here are the available events: {event_list}")
            else:
                dispatcher.utter_message(text="No events currently available.")
            return []
            
        ticket = db.tickets.find_one({"event": {"$regex": event_name, "$options": "i"}})
        
        if ticket:
            dispatcher.utter_message(text=f"Found it! {ticket['event']} costs ${ticket['price']} and we have {ticket['available']} seats left.")
        else:
            dispatcher.utter_message(text=f"I'm sorry, I couldn't find any event named '{event_name}'.")
            
        return []

class ActionSubmitBooking(Action):
    def name(self) -> Text:
        return "action_submit_booking"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        event_name = tracker.get_slot("event_name")
        quantity = tracker.get_slot("ticket_quantity")
        print(f"DEBUG submit booking: event_name={event_name}, quantity={quantity}")

        # Verify availability
        ticket = db.tickets.find_one({"event": {"$regex": event_name, "$options": "i"}})
        
        try:
            quantity_int = int(quantity)
        except (ValueError, TypeError):
            word_to_num = {
                "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, 
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "a": 1, "an": 1, "couple": 2, "few": 3
            }
            qty_str = str(quantity).lower().strip()
            if qty_str in word_to_num:
                quantity_int = word_to_num[qty_str]
            else:
                import re
                digits = re.findall(r'\d+', qty_str)
                if digits:
                    quantity_int = int(digits[0])
                else:
                    dispatcher.utter_message(text="I couldn't understand the number of tickets. Could you please specify a number?")
                    return []

        if not ticket or ticket["available"] < quantity_int:
            dispatcher.utter_message(text="I'm sorry, there aren't enough tickets available for that event.")
            return []
        
        # Book tickets
        db.bookings.insert_one({
            "event": ticket["event"],
            "quantity": quantity_int,
            "status": "booked"
        })
        
        # Update availability
        db.tickets.update_one(
            {"_id": ticket["_id"]},
            {"$inc": {"available": -quantity_int}}
        )
        
        dispatcher.utter_message(text=f"Success! Booked {quantity_int} tickets for {ticket['event']} (Query: {event_name}).")
        
        return [SlotSet("event_name", None), SlotSet("ticket_quantity", None)]

class ValidateTicketBookingForm(FormValidationAction):
    def name(self) -> Text:
        return "validate_ticket_booking_form"

    def validate_event_name(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        ticket = db.tickets.find_one({"event": {"$regex": slot_value, "$options": "i"}})
        if not ticket:
            tickets = list(db.tickets.find())
            event_list = ", ".join([t['event'] for t in tickets]) if tickets else "none"
            dispatcher.utter_message(text=f"I couldn't find an event matching '{slot_value}'. Available events: {event_list}")
            return {"event_name": None}
        return {"event_name": slot_value}

    def validate_ticket_quantity(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        try:
            qty = int(slot_value)
            if qty <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            word_to_num = {
                "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, 
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "a": 1, "an": 1, "couple": 2, "few": 3
            }
            qty_str = str(slot_value).lower().strip()
            if qty_str in word_to_num:
                qty = word_to_num[qty_str]
            else:
                import re
                digits = re.findall(r'\d+', qty_str)
                if digits:
                    qty = int(digits[0])
                else:
                    dispatcher.utter_message(text="I couldn't understand the number of tickets. Please specify a valid positive number.")
                    return {"ticket_quantity": None}
        
        event_name = tracker.get_slot("event_name")
        if event_name:
            ticket = db.tickets.find_one({"event": {"$regex": event_name, "$options": "i"}})
            if ticket and ticket["available"] < qty:
                dispatcher.utter_message(text=f"Sorry, only {ticket['available']} tickets available for {ticket['event']}.")
                return {"ticket_quantity": None}
                
        return {"ticket_quantity": str(qty)}
