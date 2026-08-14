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
| `greet` | User greets the bot | "Hi", "Hello", "Hey there" | `greet` | | |
| `goodbye` | User ends conversation | "Bye", "See you", "Goodbye" | `goodbye` | | |
| `start_booking` | User initiates ticket purchase | "I want to buy tickets", "Book a show", "Get tickets" | `start_booking` | | |
| `inform` (or `inform_slot`) | User provides requested details (event name, quantity) | "Concert A", "3 tickets", "Pop Night" | `inform` | | |
| `query_events` | User asks about available events or schedule | "What events do you have?", "Any concerts this weekend?" | `query_events` | | |
| `affirm` | User confirms booking | "Yes", "Sure", "Confirm" | `confirm_booking` | | |
| `deny` | User cancels or aborts booking | "No", "Cancel", "Nevermind" | `cancel_booking` | | |
| `change_event` | User wants a different event mid-booking | "Change event", "Pick another event" | `change_event` | | |
| `inform_ticket_query` | User asks for ticket/event information | "Check prices for tickets", "I need event information" | `inform_ticket_query` | | |

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