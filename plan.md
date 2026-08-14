# Chatbot Development — Online Ticketing System (Plan)

## 1. Project Overview

Build an **Online Ticketing System** chatbot using 3 different approaches, connected to a shared UI and cloud database for side-by-side comparison.

| Member | Approach | Tool / Technique |
|--------|----------|------------------|
| **Member 1** (You) | Platform-based | **Rasa** (open-source NLU + Custom Actions + Forms) |
| **Member 2** | ML-based | Custom **NLP model** (TF-IDF + classifier / LSTM) |
| **Member 3** | Platform-based | **Google Dialogflow** (cloud NLU) |

---

## 2. Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Shared UI | **Streamlit** | Python-native frontend, shared across all members |
| Unified API | **FastAPI** | Routes requests to the correct chatbot, handles DB |
| Cloud Database | **MongoDB Atlas** (Free Tier) | Shared persistent storage for tickets + conversations |
| Chatbot 1 | **Rasa** | Rasa NLU + Core + Action Server |
| Chatbot 2 | **NLP ML Model** | Custom model served via FastAPI |
| Chatbot 3 | **Dialogflow** | Google cloud chatbot via Dialogflow REST API |

---

## 3. Architecture

```
+---------------------+
|   Streamlit UI       |  <-- Shared by all teammates
|  (frontend/app.py)   |
+----------+----------+
           |
           | HTTP
           v
+---------------------+
|   FastAPI Backend    |  <-- Unified entry point
|  (backend/main.py)   |
+----+----+----+------+
     |    |    |
     |    |    +--- MongoDB Atlas (shared)
     |    |            collections: tickets, conversations, feedback
     |    |
     |    +--- Member 3: Dialogflow  (via google.cloud.dialogflow)
     |
     +--- Member 2: NLP ML Model    (local FastAPI route)
     |
     +--- Member 1: Rasa            (http://localhost:5005/webhooks/chat)
          |
          +--- Rasa Action Server (for custom DB logic & booking)
```

### Data Flow
1. User types a message in Streamlit
2. Streamlit sends `POST /chat` to FastAPI with `{ "message": "...", "bot": "rasa|nlp|dialogflow" }`
3. FastAPI logs the request to MongoDB, forwards to the selected chatbot
4. Chatbot responds → FastAPI logs the response → returns to Streamlit

---

## 4. Unified Team Contract: Standardized Intents & Entities

To ensure seamless side-by-side comparison across all 3 chatbot approaches (Rasa, Custom NLP Model, and Dialogflow), all teammates must adhere to this standardized set of **Intents** and **Entities**.

### Standardized Intents
| Intent Name | Description / User Goal | Example Utterances | Rasa Equivalent | NLP Equivalent | Dialogflow Equivalent |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `greet` | User greets the bot | "Hi", "Hello", "Hey there" | `greet` | `greeting` | |
| `goodbye` | User ends conversation | "Bye", "See you", "Goodbye" | `goodbye` | `goodbye` | |
| `start_booking` | User initiates ticket purchase | "I want to buy tickets", "Book a show", "Get tickets" | `start_booking` | `book_ticket` | |
| `inform` (or `inform_slot`) | User provides requested details (event name, quantity) | "Concert A", "3 tickets", "Pop Night" | `inform` | *(no classifier intent — handled contextually as a slot answer while a booking/lookup session is active)* | |
| `query_events` | User asks about available events or schedule | "What events do you have?", "Any concerts this weekend?" | `query_events` | `list_events` | |
| `affirm` | User confirms booking | "Yes", "Sure", "Confirm" | `confirm_booking` | *(no classifier intent — matched via affirmative-prefix text match during an active booking confirmation)* | |
| `deny` | User cancels or aborts booking | "No", "Cancel", "Nevermind" | `cancel_booking` | *(no classifier intent — matched via negative/cancel-word text match during an active session)* | |
| `change_event` | User wants a different event mid-booking | "Change event", "Pick another event" | `change_event` | *(no classifier intent — detected by re-matching a different known event name mid-**booking** session only; a lookup session just re-answers as a plain `inform`)* | |
| `inform_ticket_query` | User asks for ticket/event information | "Check prices for tickets", "I need event information" | `inform_ticket_query` | `check_price` / `event_schedule` / `event_location` *(split into 3)* | |

**NLP note:** the classifier has 10 trained intents against the 9 standardized ones — 3 extra exist outside the contract: `bot_capabilities`, `thanks`, `cancel_ticket`.

### Standardized Entities
| Entity Name | Description | Expected Values / Types |
| :--- | :--- | :--- |
| `event_name` | Name or shorthand of the event | `Concert A`, `Concert B`, `Rock Fest`, `Pop Night` |
| `ticket_quantity` | Number of tickets requested | Integer (`1`, `3`) or word number (`one`, `three`, `couple`) |
| `timeframe` | Date or time period constraint | `tomorrow`, `this month`, `May` |
| `category` | Event category filter | `music`, `sports`, `theater` |
| `date` | Specific event date | `2026-06-15` |
| `venue` | Event location filter | `Arena Green`, `Stadium XYZ` |
| `price` | Ticket price filter | `RM50`, `RM100` |

---