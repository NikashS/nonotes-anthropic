from __future__ import annotations

import os
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = f"sqlite:////tmp/nonotes-test-{uuid4().hex}.db"

from backend.main import app

client = TestClient(app)


def interaction(message: str, focused_block_ids: list[str] | None = None) -> dict:
    response = client.post("/interactions", json={
        "message": message,
        "context": {
            "canvas_id": "main",
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "focused_artifact_id": "artifact_no_notes",
            "focused_block_ids": focused_block_ids or [],
            "recent_focus_history": [],
        },
    })
    assert response.status_code == 200
    return {"text": response.text, "events": [line for line in response.text.splitlines() if line]}


def test_canvas_is_seeded_with_generative_blocks() -> None:
    response = client.get("/canvas")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "main"
    assert len(body["artifacts"]) == 1
    assert len(body["blocks"]) >= 4
    assert {block["kind"] for block in body["blocks"]} >= {"hero", "process", "comparison", "callout"}
    assert all("html" in block for block in body["blocks"])


def test_follow_up_stream_extends_focused_artifact() -> None:
    result = interaction("Add a privacy layer to this architecture", ["block_flow"])
    assert any('"event": "block.started"' in line for line in result["events"])
    assert any('"mode": "extend"' in line for line in result["events"])
    assert any('"transition": "continuation"' in line for line in result["events"])
    canvas = client.get("/canvas").json()
    artifact = next(item for item in canvas["artifacts"] if item["id"] == "artifact_no_notes")
    assert artifact["title"] == "The No Notes idea"
    assert len(canvas["blocks"]) >= 6


def test_modify_replaces_one_block_in_place() -> None:
    before = len(client.get("/canvas").json()["blocks"])
    result = interaction("Make this explanation simpler", ["block_vision"])
    after_canvas = client.get("/canvas").json()
    assert '"replacing": true' in result["text"]
    assert '"mode": "modify"' in result["text"]
    assert len(after_canvas["blocks"]) == before
    block = next(item for item in after_canvas["blocks"] if item["id"] == "block_vision")
    assert "The simple version" in block["html"]


def test_separate_topic_gets_new_region_and_topic_shift() -> None:
    result = interaction("Start a separate topic: plan a two-week Japan trip")
    assert '"mode": "new"' in result["text"]
    assert '"transition": "topic-shift"' in result["text"]
    canvas = client.get("/canvas").json()
    assert len(canvas["artifacts"]) == 2
    original = next(item for item in canvas["artifacts"] if item["id"] == "artifact_no_notes")
    created = next(item for item in canvas["artifacts"] if item["id"] != "artifact_no_notes")
    assert created["title"] == "Two weeks in Japan"
    assert created["x"] > original["x"] + original["width"]
    assert any(block["artifact_id"] == created["id"] and block["kind"] == "timeline" for block in canvas["blocks"])
