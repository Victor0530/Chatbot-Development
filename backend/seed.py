import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_collection

def seed_db():
    tickets_col = get_collection("tickets")
    
    # Clear existing tickets
    tickets_col.delete_many({})
    
    sample_tickets = [
        {"event": "Concert A - Pop Night", "date": "2026-05-20", "venue": "Stadium XYZ", "price": 150.00, "available": 120, "category": "music"},
        {"event": "Concert B - Rock Fest", "date": "2026-06-15", "venue": "Arena Green", "price": 85.00, "available": 300, "category": "music"},
        {"event": "Broadway Musical", "date": "2026-07-10", "venue": "Grand Theater", "price": 120.00, "available": 50, "category": "theater"},
        {"event": "Championship Basketball", "date": "2026-08-01", "venue": "City Center", "price": 200.00, "available": 80, "category": "sports"},
        {"event": "Standup Comedy Gala", "date": "2026-09-05", "venue": "Laugh Lounge", "price": 45.00, "available": 150, "category": "comedy"}
    ]
    
    tickets_col.insert_many(sample_tickets)
    print("Database seeded with sample tickets successfully.")

if __name__ == "__main__":
    seed_db()
