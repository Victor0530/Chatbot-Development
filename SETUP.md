# Project Setup & Development Guide

This project is fully containerized using Docker. This ensures that the environment is consistent across all machines and development setups.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- MongoDB Atlas connection string (`MONGO_URI`) configured in `backend/.env`.

## Running the Project

1.  **Start the entire stack:**
    Open your terminal in the project root directory and run:
    ```bash
    docker compose up --build
    ```
    This command will:
    - Build images for Backend, Frontend, Rasa, and the Rasa Action Server.
    - Connect services to MongoDB Atlas.
    - Start the application services.

2.  **Accessing the services & Initializing Rasa:**
    - **Backend API:** `http://localhost:8000`
    - **Frontend UI:** `http://localhost:8501`
    - **Rasa Chatbot API:** `http://localhost:5005`
    - **Action Server:** Reachable only inside the Docker network (no host port mapping); Rasa connects to it via `endpoints.yml` (`http://actions:5055/webhook`).
    - **NLP (ML) Chatbot API:** `http://localhost:8600`

    *Important (First-time setup):* Because trained Rasa models are excluded from version control, you must train the model inside the container after starting the stack for the first time:
    ```bash
    docker compose exec rasa rasa train
    docker compose restart rasa actions
    ```

    Likewise, the NLP chatbot's TF-IDF/ANN model is excluded from version control and must be trained after the first start:
    ```bash
    docker compose exec nlp-chatbot python train.py
    docker compose restart nlp-chatbot
    ```

## Stopping the Project

- To stop the containers in the foreground, press `Ctrl + C` in your terminal.
- To stop and remove all containers, networks, and volumes (cleanup), run:
    ```bash
    docker compose down
    ```

## Development Notes

- **Dependencies:** All dependencies are managed within the respective `Dockerfile`s and `requirements.txt` files in each service directory (`backend/`, `frontend/`, `rasa-chatbot/`).
- **Rasa & Actions:** Any changes to dialogue flow (stories/rules/forms) require retraining the Rasa model (`rasa train`). Changes to custom action or validation logic require restarting the `actions` container (`docker compose restart actions`).

## Dialogflow Bot Setup (Member 3)

The Dialogflow bot needs a couple of things beyond `MONGO_URI` before it will respond, all configured in `backend/.env` (see `backend/.env.example`):

- `DIALOGFLOW_PROJECT_ID` — the GCP project ID of the Dialogflow ES agent.
- `GOOGLE_APPLICATION_CREDENTIALS` — path to a GCP service account key JSON file (resolved relative to `backend/` if not absolute).
  - The service account needs the **Dialogflow API Admin** role on the project.
  - Download the key file from the GCP console and place it locally (e.g. `backend/secret/your-key.json`) — **never commit it**. `backend/secret/` and `*-service-account*.json` are already in `.gitignore`.

Without both of these set, chatting with the `dialogflow` bot in the frontend will return a "Sorry, something went wrong." response instead of a real reply.

