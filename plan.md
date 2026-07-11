# Chatbot Development — Online Ticketing System (Plan)

## 1. Project Overview

Build an **Online Ticketing System** chatbot using 3 different approaches, connected to a shared UI and cloud database for side-by-side comparison.

| Member | Approach | Tool / Technique |
|--------|----------|------------------|
| **Member 1** (You) | Platform-based | **Rasa** (open-source NLU) |
| **Member 2** | ML-based | Custom **NLP model** (TF-IDF + classifier / LSTM) |
| **Member 3** | Platform-based | **Google Dialogflow** (cloud NLU) |

---

## 2. Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Shared UI | **Streamlit** | Python-native frontend, shared across all members |
| Unified API | **FastAPI** | Routes requests to the correct chatbot, handles DB |
| Cloud Database | **MongoDB Atlas** (Free Tier) | Shared persistent storage for tickets + conversations |
| Chatbot 1 | **Rasa** | Exposes REST API (`POST /webhooks/chat`) |
| Chatbot 2 | **NLP ML Model** | Custom model served via FastAPI or Flask |
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
```

### Data Flow
1. User types a message in Streamlit
2. Streamlit sends `POST /chat` to FastAPI with `{ "message": "...", "bot": "rasa|nlp|dialogflow" }`
3. FastAPI logs the request to MongoDB, forwards to the selected chatbot
4. Chatbot responds → FastAPI logs the response → returns to Streamlit

---

## 4. Database Schema (MongoDB Atlas)

### `tickets`
```json
{
  "_id": ObjectId,
  "event": "Concert A",
  "date": "2026-05-20",
  "venue": "Stadium XYZ",
  "price": 150.00,
  "available": 120,
  "category": "music"
}
```

### `conversations`
```json
{
  "_id": ObjectId,
  "session_id": "abc123",
  "bot_type": "rasa",
  "messages": [
    { "role": "user", "text": "Hi", "timestamp": "..." },
    { "role": "bot", "text": "Hello! How can I help?", "timestamp": "..." }
  ],
  "intents": ["greet"],
  "created_at": "..."
}
```

### `feedback`
```json
{
  "_id": ObjectId,
  "session_id": "abc123",
  "bot_type": "rasa",
  "rating": 4,
  "comment": "Fast and accurate",
  "created_at": "..."
}
```

---

## 5. Folder Structure

```
/chatbot-ticketing-system
├── frontend/                  # Shared Streamlit UI
│   └── app.py
├── backend/                   # FastAPI unified backend
│   ├── main.py                # Entry point, routes
│   ├── database.py            # MongoDB connection
│   ├── models.py              # Pydantic models
│   ├── requirements.txt
│   └── .env                   # MongoDB URI + keys
├── rasa-chatbot/              # Member 1 — Rasa
│   ├── actions/
│   ├── data/
│   │   ├── nlu.yml
│   │   ├── stories.yml
│   │   └── rules.yml
│   ├── config.yml
│   ├── domain.yml
│   ├── endpoints.yml
│   └── credentials.yml
├── nlp-chatbot/               # Member 2 — NLP ML-based
│   ├── train.py               # Train intent classifier
│   ├── model.pkl               # Trained model
│   ├── intents.json           # Training data
│   ├── server.py              # Flask/FastAPI wrapper
│   └── preprocess.py          # Tokenization, cleaning
├── dialogflow-chatbot/        # Member 3 — Dialogflow
│   ├── agent.zip              # Exported Dialogflow agent
│   ├── server.py              # FastAPI ↔ Dialogflow bridge
│   └── service-account.json   # GCP service account key
├── requirements.txt           # Shared Python deps
├── plan.md                    # This file
└── README.md                  # Setup instructions
```

---

## 6. API Contract

All chatbots must expose this interface for the FastAPI backend to call:

### Request (FastAPI → Chatbot)
```
POST /chat
Content-Type: application/json

{
  "message": "I want to buy 2 tickets to Concert A",
  "session_id": "user-session-001"
}
```

### Response (Chatbot → FastAPI)
```json
{
  "response": "Sure! 2 tickets to Concert A — that'll be $300. Confirm?",
  "intent": "book_tickets",
  "confidence": 0.92
}
```

### FastAPI Unified Endpoint (Streamlit → FastAPI)
```
POST /api/chat
Content-Type: application/json

{
  "message": "I want to buy 2 tickets to Concert A",
  "bot": "rasa"  // or "nlp" or "dialogflow"
}
```

Response: same format as above.

---

## 7. Timeline (4 Weeks)

### Phase 1 — Foundation (Week 1)
| Day | Task | Owner |
|-----|------|-------|
| 1 | Set up MongoDB Atlas cluster (free tier), share connection string | All |
| 1 | Create shared repo, scaffold folder structure | All |
| 2 | Build FastAPI backend: MongoDB connection + `/api/chat` route | All (pair) |
| 3 | Build Streamlit UI: chat interface + bot selector dropdown | All (pair) |
| 4 | Test UI ↔ Backend connection end-to-end | All |
| 5 | Seed MongoDB with sample ticket data | All |

### Phase 2 — Chatbot Development (Week 2–3)
| Week | Task | Owner |
|------|------|-------|
| W2 | Build Rasa chatbot: intents, stories, domain, actions, test locally | Member 1 (You) |
| W2 | Build NLP chatbot: collect intents data, train classifier, wrap in server | Member 2 |
| W2 | Build Dialogflow chatbot: create agent, configure intents/entities, export | Member 3 |
| W3 | Integrate Rasa with FastAPI (connect to `/api/chat`) | Member 1 (You) |
| W3 | Integrate NLP model with FastAPI | Member 2 |
| W3 | Integrate Dialogflow with FastAPI (service account auth) | Member 3 |

### Phase 3 — Integration (Week 3–4)
| Day | Task | Owner |
|-----|------|-------|
| 1 | Wire all 3 chatbots to Streamlit bot selector dropdown | All |
| 2 | Log every conversation to MongoDB `conversations` collection | All |
| 3 | Add feedback form to Streamlit UI (rating 1–5 + comment) | All |
| 4 | End-to-end testing across all 3 chatbots | All |

### Phase 4 — Evaluation & Documentation (Week 4)
| Day | Task | Owner |
|-----|------|-------|
| 1 | Compare intent recognition accuracy (F1, Precision, Recall) | All |
| 2 | Compare response quality (BLEU/ROUGE if applicable) | All |
| 3 | Analyze user feedback from MongoDB | All |
| 4 | Compile report / documentation | All |

---

## 8. Setup Instructions (for teammates)

```bash
# 1. Clone the repo
git clone <repo-url>
cd chatbot-ticketing-system

# 2. Install shared dependencies
pip install -r requirements.txt

# 3. Backend setup
cd backend
cp .env.example .env   # Add MongoDB Atlas URI
uvicorn main:app --reload --port 8000

# 4. Frontend (separate terminal)
cd frontend
streamlit run app.py

# 5. Each chatbot has its own setup in its respective folder
```

### Shared `requirements.txt`
```
streamlit
fastapi
uvicorn
pymongo[srv]
python-dotenv
requests
pandas
```

---

## 9. Success Criteria

- [ ] Streamlit UI can switch between 3 chatbots and display responses
- [ ] All conversations are logged to MongoDB Atlas
- [ ] Each chatbot can answer ticket-related queries (availability, booking, FAQ)
- [ ] Feedback is collected and stored
- [ ] Evaluation metrics are computed and compared
