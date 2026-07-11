from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class ChatRequest(BaseModel):
    message: str
    bot: str = Field(..., description="Must be one of: rasa, nlp, dialogflow")
    session_id: str = "default"

class ChatResponse(BaseModel):
    response: str
    intent: Optional[str] = None
    confidence: Optional[float] = None

class FeedbackRequest(BaseModel):
    session_id: str
    bot_type: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

class Ticket(BaseModel):
    event: str
    date: str
    venue: str
    price: float
    available: int
    category: str
