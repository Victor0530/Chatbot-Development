import os
import re
from pymongo import MongoClient
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop
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

class ActionCancelBooking(Action):
    def name(self) -> Text:
        return "action_cancel_booking"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        dispatcher.utter_message(text="Booking cancelled. Let me know if you'd like to start over.")
        
        return [ActiveLoop(None), SlotSet("event_name", None), SlotSet("ticket_quantity", None)]

class ActionSearchTickets(Action):
    def name(self) -> Text:
        return "action_search_tickets"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        event_name = tracker.get_slot("event_name")
        category = tracker.get_slot("category")
        venue = tracker.get_slot("venue")
        date = tracker.get_slot("date") or tracker.get_slot("timeframe")
        
        latest_message = tracker.latest_message.get("text", "").lower()

        # Robust fallback keyword extraction if slots are empty
        if not category:
            for cat in ["music", "theater", "sports", "comedy"]:
                if cat in latest_message:
                    category = cat
                    break
                    
        if not venue:
            for v in ["arena green", "stadium xyz", "grand theater", "city center", "laugh lounge"]:
                if v in latest_message:
                    venue = v
                    break

        if not date:
            month_map = {"january": "01", "february": "02", "march": "03", "april": "04", "may": "05", "june": "06", "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12"}
            for m_name, m_num in month_map.items():
                if m_name in latest_message:
                    date = m_num
                    break

        price = tracker.get_slot("price")

        if not price:
            import re
            price_match = re.search(r'(?:under|below|less than|max|up to)\s*(?:RM)?\s*(\d+(?:\.\d+)?)', latest_message)
            if price_match:
                price = price_match.group(1)

        query: Dict[str, Any] = {}
        if event_name:
            query["event"] = {"$regex": event_name, "$options": "i"}
        if category:
            query["category"] = {"$regex": category, "$options": "i"}
        if venue:
            query["venue"] = {"$regex": venue, "$options": "i"}
        if price:
            import re
            price_match = re.search(r'[\d.]+', str(price))
            if price_match:
                query["price"] = {"$lte": float(price_match.group())}
        if date:
            date_lower = str(date).lower()
            month_map = {"january": "01", "february": "02", "march": "03", "april": "04", "may": "05", "june": "06", "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12"}
            for m_name, m_num in month_map.items():
                if m_name in date_lower:
                    date = m_num
                    break
            date_pattern = f"2026-{date}" if len(date) == 2 and date.isdigit() else date
            query["date"] = {"$regex": date_pattern, "$options": "i"}
        
        # Check for seat/availability query extremes
        if "most" in latest_message and ("seat" in latest_message or "available" in latest_message):
            ticket = db.tickets.find_one(sort=[("available", -1)])
            if ticket:
                dispatcher.utter_message(text=f"The event with the most available seats is {ticket['event']} at {ticket['venue']} with {ticket['available']} seats left (RM{ticket['price']}).")
            else:
                dispatcher.utter_message(text="No events found.")
            return []
            
        if "least" in latest_message and ("seat" in latest_message or "available" in latest_message):
            ticket = db.tickets.find_one(sort=[("available", 1)])
            if ticket:
                dispatcher.utter_message(text=f"The event with the least available seats is {ticket['event']} at {ticket['venue']} with {ticket['available']} seats left (RM{ticket['price']}).")
            else:
                dispatcher.utter_message(text="No events found.")
            return []

        tickets = list(db.tickets.find(query))
        
        if not tickets:
            dispatcher.utter_message(text="I couldn't find any events matching your criteria.")
            return []
            
        if len(tickets) == 1:
            t = tickets[0]
            dispatcher.utter_message(text=f"Found: {t['event']} | Genre: {t['category'].capitalize()} | Date: {t['date']} | Venue: {t['venue']} | Price: RM{t['price']:.2f} | Available Seats: {t['available']}")
        else:
            lines = []
            for t in tickets:
                lines.append(f"• {t['event']} ({t['category'].capitalize()}) - Date: {t['date']} @ {t['venue']} | RM{t['price']:.2f} | {t['available']} seats left")
            dispatcher.utter_message(text="Here are the matching events:\n" + "\n".join(lines))
            
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
        if not slot_value or not str(slot_value).strip():
            return {"event_name": None}

        # Bypass validation silently if the user is attempting another action/intent
        latest_intent = tracker.latest_message.get("intent", {}).get("name")
        if latest_intent in ["query_events", "cancel_booking", "change_event", "goodbye"]:
            return {"event_name": None}

        raw_text = tracker.latest_message.get("text", "").strip()
        text_lower = raw_text.lower()
        if any(k in text_lower for k in ["cancel", "nevermind", "stop", "abort", "change", "switch", "different", "under", "below", "cheaper", "most", "least"]):
            return {"event_name": None}

        tickets = list(db.tickets.find())
        event_list = ", ".join([t['event'] for t in tickets]) if tickets else "none"

        matched_ticket = None
        search_terms = [raw_text, str(slot_value).strip()]

        for term in search_terms:
            if not term:
                continue
            clean_term = re.sub(r'\b(i|want|to|book|ticket|tickets|for|a|the|show|event)\b', '', term, flags=re.I).strip()
            if not clean_term:
                clean_term = term

            for t in tickets:
                event_title = t['event']
                parts = [p.strip() for p in event_title.split('-')]
                if re.search(r'\b' + re.escape(clean_term) + r'\b', event_title, flags=re.I) or any(clean_term.lower() == p.lower() for p in parts):
                    matched_ticket = t
                    break
            if matched_ticket:
                break

        if not matched_ticket:
            dispatcher.utter_message(text=f"I couldn't find an event matching '{raw_text}'. Available events: {event_list}")
            return {"event_name": None}

        return {"event_name": matched_ticket["event"]}

    def validate_ticket_quantity(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        if not slot_value or not str(slot_value).strip():
            return {"ticket_quantity": None}

        # Bypass validation silently if user is attempting another action/intent
        latest_intent = tracker.latest_message.get("intent", {}).get("name")
        if latest_intent in ["query_events", "cancel_booking", "change_event", "goodbye"]:
            return {"ticket_quantity": None}

        text = tracker.latest_message.get("text", "").lower()
        if any(k in text for k in ["cancel", "nevermind", "stop", "abort", "change", "switch", "different"]):
            return {"ticket_quantity": None}

        qty = None
        qty_str = str(slot_value).lower().strip()

        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, 
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "a": 1, "an": 1, "couple": 2, "few": 3
        }

        try:
            qty = int(qty_str)
        except (ValueError, TypeError):
            if qty_str in word_to_num:
                qty = word_to_num[qty_str]
            else:
                import re
                digits = re.findall(r'\d+', qty_str)
                if digits:
                    qty = int(digits[0])

        if qty is None:
            dispatcher.utter_message(text="I couldn't understand the number of tickets. Please specify a valid positive number.")
            return {"ticket_quantity": None}

        if qty <= 0:
            dispatcher.utter_message(text="Please specify a valid positive number of tickets (at least 1).")
            return {"ticket_quantity": None}
        
        event_name = tracker.get_slot("event_name")
        if event_name:
            ticket = db.tickets.find_one({"event": {"$regex": event_name, "$options": "i"}})
            if ticket and ticket["available"] < qty:
                dispatcher.utter_message(text=f"Sorry, only {ticket['available']} tickets available for {ticket['event']}.")
                return {"ticket_quantity": None}
                
        return {"ticket_quantity": str(qty)}
