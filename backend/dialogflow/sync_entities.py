"""
Syncs the Dialogflow "event_name" entity type with live event data from MongoDB,
so the ticket catalog doesn't have to be maintained by hand in the console.

Run manually whenever the catalog changes:
    python sync_entities.py
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
sys.path.insert(0, os.path.dirname(_THIS_DIR))

from google.cloud import dialogflow
from google.protobuf import field_mask_pb2

from config import DIALOGFLOW_PROJECT_ID
from database import get_collection

ENTITY_TYPE_DISPLAY_NAME = "event_name"


def _find_entity_type(client: "dialogflow.EntityTypesClient", project_id: str):
    parent = f"projects/{project_id}/agent"
    for entity_type in client.list_entity_types(request={"parent": parent}):
        if entity_type.display_name == ENTITY_TYPE_DISPLAY_NAME:
            return entity_type
    return None


def _build_entities(tickets) -> list:
    entities_by_value = {}

    for ticket in tickets:
        value = (ticket.get("event") or "").strip()
        if not value:
            continue

        synonyms = entities_by_value.setdefault(value, {value})

        # A short variant like "Concert A" out of "Concert A - Pop Night" is a
        # natural thing users type instead of the full event title.
        if " - " in value:
            short_variant = value.split(" - ", 1)[0].strip()
            if short_variant:
                synonyms.add(short_variant)

    return [
        dialogflow.EntityType.Entity(value=value, synonyms=sorted(synonyms))
        for value, synonyms in entities_by_value.items()
    ]


def sync_entities():
    if not DIALOGFLOW_PROJECT_ID:
        raise RuntimeError("DIALOGFLOW_PROJECT_ID is not set.")
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is not set.")

    client = dialogflow.EntityTypesClient()

    entity_type = _find_entity_type(client, DIALOGFLOW_PROJECT_ID)
    if entity_type is None:
        raise RuntimeError(
            f'No entity type named "{ENTITY_TYPE_DISPLAY_NAME}" found for project '
            f'"{DIALOGFLOW_PROJECT_ID}". Create it once in the Dialogflow console first.'
        )

    tickets = list(get_collection("tickets").find())
    entities = _build_entities(tickets)

    if not entities:
        print("No events with a valid 'event' field found in the tickets collection. "
              "Aborting without touching the existing entity type.")
        return

    entity_type.entities = entities
    client.update_entity_type(
        request={
            "entity_type": entity_type,
            "language_code": "en",
            "update_mask": field_mask_pb2.FieldMask(paths=["entities"]),
        }
    )

    print(f"Synced {len(entities)} entities to '{ENTITY_TYPE_DISPLAY_NAME}' ({entity_type.name}).")


if __name__ == "__main__":
    sync_entities()
