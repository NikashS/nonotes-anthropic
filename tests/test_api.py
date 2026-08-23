from __future__ import annotations

import os
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = f"sqlite:////tmp/nonotes-test-{uuid4().hex}.db"

from backend.main import app


client = TestClient(app)


def test_canvas_is_seeded() -> None:
    response = client.get("/canvas")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "main"
    assert len(body["elements"]) >= 5
    assert len(body["connectors"]) >= 2


def test_follow_up_stream_extends_focused_artifact() -> None:
    response = client.post("/interactions", json={
        "message": "Add a privacy layer to this architecture",
        "context": {
            "canvas_id": "main",
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "focused_artifact_id": "artifact_no_notes",
            "selected_element_ids": ["element_continue"],
            "recent_focus_history": [],
        },
    })
    assert response.status_code == 200
    events = [json_line for json_line in response.text.splitlines() if json_line]
    assert any('"event": "element.created"' in line for line in events)
    assert any('"mode": "extend"' in line for line in events)
    assert any('"artifact_id": "artifact_no_notes"' in line for line in events)
    artifact = next(item for item in client.get("/canvas").json()["artifacts"] if item["id"] == "artifact_no_notes")
    assert artifact["title"] == "The No Notes idea"


def test_modify_updates_in_place() -> None:
    response = client.post("/interactions", json={
        "message": "Make this explanation simpler",
        "context": {
            "canvas_id": "main",
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "focused_artifact_id": "artifact_no_notes",
            "selected_element_ids": ["element_vision"],
            "recent_focus_history": [],
        },
    })
    assert response.status_code == 200
    assert '"event": "element.patched"' in response.text
    assert '"mode": "modify"' in response.text
