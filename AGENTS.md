# OpenCode Agent Instructions

## Tech Stack
- **Backend:** FastAPI, Python
- **Frontend:** Streamlit, Python
- **Database:** MongoDB (via `pymongo`)

## Running the Application
The application consists of a backend API and a frontend UI.

1.  **Backend:**
    ```bash
    cd backend
    uvicorn main:app --reload --port 8000
    ```
2.  **Frontend:**
    ```bash
    cd frontend
    streamlit run app.py
    ```

## Development Quirks
- **Database:** Requires a running MongoDB instance. The backend expects connection details in a `.env` file (see `backend/.env.example`).
- **Seeding:** The database can be seeded by running `python backend/seed.py` or by sending a POST request to `/api/seed`.
- **Environment:** Ensure all dependencies in `requirements.txt` are installed (`pip install -r requirements.txt`).
