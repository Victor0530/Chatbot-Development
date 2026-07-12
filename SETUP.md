# Project Setup & Development Guide

This project is fully containerized using Docker. This ensures that the environment is consistent across all machines and development setups.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

## Running the Project

1.  **Start the entire stack:**
    Open your terminal in the project root directory and run:
    ```bash
    docker-compose up --build
    ```
    This command will:
    - Build images for Backend, Frontend, and the Rasa chatbot.
    - Start a MongoDB container.
    - Start the application services.

2.  **Accessing the services:**
    - **Backend API:** `http://localhost:8000`
    - **Frontend UI:** `http://localhost:8501`
    - **Rasa Chatbot API:** `http://localhost:5005`

## Stopping the Project

- To stop the containers in the foreground, press `Ctrl + C` in your terminal.
- To stop and remove all containers, networks, and volumes (cleanup), run:
    ```bash
    docker-compose down
    ```

## Development Notes

- **Dependencies:** All dependencies are managed within the respective `Dockerfile`s and `requirements.txt` files in each service directory (`backend/`, `frontend/`, `rasa-chatbot/`).
- **No Virtual Environment Needed:** You do not need a local `venv` to run the project. Docker handles all isolation. You only need a `venv` locally if you want your IDE to provide linting and autocomplete support for the code.
