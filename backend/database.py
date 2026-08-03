import os
import json
from pymongo import MongoClient
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)

MONGO_URI = os.getenv("MONGO_URI", "")
USE_LOCAL = False

db = None
client = None

if MONGO_URI:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        # Check connection
        client.server_info()
        db = client["chatbot_ticketing"]
        print("Connected to MongoDB Atlas successfully.")
    except Exception as e:
        print(f"Failed to connect to MongoDB Atlas: {e}. Falling back to local JSON database.")
        USE_LOCAL = True
else:
    print("MONGO_URI not found. Using local JSON database.")
    USE_LOCAL = True

LOCAL_DB_FILE = os.path.join(os.path.dirname(__file__), "local_db.json")

def initialize_local_db():
    if not os.path.exists(LOCAL_DB_FILE):
        initial_data = {
            "tickets": [
                {"event": "Concert A - Pop Night", "date": "2026-05-20", "venue": "Stadium XYZ", "price": 150.00, "available": 120, "category": "music"},
                {"event": "Concert B - Rock Fest", "date": "2026-06-15", "venue": "Arena Green", "price": 85.00, "available": 300, "category": "music"},
                {"event": "Broadway Musical", "date": "2026-07-10", "venue": "Grand Theater", "price": 120.00, "available": 50, "category": "theater"},
                {"event": "Championship Basketball", "date": "2026-08-01", "venue": "City Center", "price": 200.00, "available": 80, "category": "sports"}
            ],
            "conversations": [],
            "feedback": []
        }
        with open(LOCAL_DB_FILE, "w") as f:
            json.dump(initial_data, f, indent=4)

if USE_LOCAL:
    initialize_local_db()

def get_collection(name: str):
    if not USE_LOCAL and db is not None:
        return db[name]
    
    # Mock collection class for JSON operations
    class LocalCollection:
        def __init__(self, name: str):
            self.name = name
            
        def _read_data(self):
            initialize_local_db()
            with open(LOCAL_DB_FILE, "r") as f:
                return json.load(f)
                
        def _write_data(self, data):
            with open(LOCAL_DB_FILE, "w") as f:
                json.dump(data, f, indent=4)

        def _match(self, item, query):
            if not query:
                return True
            for k, v in query.items():
                item_val = item.get(k)
                if isinstance(v, dict) and "$regex" in v:
                    import re
                    pattern = v["$regex"]
                    flags = re.IGNORECASE if v.get("$options") == "i" else 0
                    if not item_val or not re.search(pattern, str(item_val), flags):
                        return False
                elif item_val != v:
                    return False
            return True

        def find(self, query=None):
            data = self._read_data()
            items = data.get(self.name, [])
            if not query:
                return items
            filtered = []
            for item in items:
                if self._match(item, query):
                    filtered.append(item)
            return filtered

        def find_one(self, query):
            results = self.find(query)
            return results[0] if results else None

        def insert_one(self, doc):
            data = self._read_data()
            if self.name not in data:
                data[self.name] = []
            data[self.name].append(doc)
            self._write_data(data)
            return doc

        def update_one(self, query, update):
            data = self._read_data()
            items = data.get(self.name, [])
            updated = False
            for item in items:
                if self._match(item, query):
                    if "$set" in update:
                        for uk, uv in update["$set"].items():
                            item[uk] = uv
                        updated = True
                    if "$inc" in update:
                        for uk, uv in update["$inc"].items():
                            item[uk] = item.get(uk, 0) + uv
                        updated = True
                    break
            if updated:
                self._write_data(data)

        def insert_many(self, docs):
            data = self._read_data()
            if self.name not in data:
                data[self.name] = []
            data[self.name].extend(docs)
            self._write_data(data)
            return docs

        def delete_many(self, query=None):
            data = self._read_data()
            if not query:
                data[self.name] = []
            else:
                items = data.get(self.name, [])
                new_items = []
                for item in items:
                    if not self._match(item, query):
                        new_items.append(item)
                data[self.name] = new_items
            self._write_data(data)

    return LocalCollection(name)
