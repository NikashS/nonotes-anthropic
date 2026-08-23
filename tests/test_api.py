from __future__ import annotations

import os
from uuid import uuid4

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = f"sqlite:////tmp/nonotes-test-{uuid4().hex}.db"

from backend.main import app
from backend.planner import _validate_plan_input

client = TestClient(app)


def interaction(message: str, focused_artifact_id: str = "artifact_no_notes", focused_block_ids: list[str] | None = None) -> dict:
    response = client.post("/interactions", json={
        "message": message,
        "context": {
            "canvas_id": "main",
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "focused_artifact_id": focused_artifact_id,
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
    assert body["artifacts"][0]["kind"] == "welcome"


def test_legacy_comparison_rows_are_normalized_for_model_output() -> None:
    plan = _validate_plan_input({
        "mode": "new",
        "title": "Database tradeoffs",
        "summary": "A comparison",
        "blocks": [{
            "ref": "comparison",
            "kind": "comparison",
            "items": ["Relational|Document", "Strong joins|Flexible shape"],
        }],
    })
    assert plan.blocks[0].items[1].title == "Strong joins"
    assert plan.blocks[0].items[1].body == "Flexible shape"


def test_first_question_leaves_welcome_and_uses_a_new_region() -> None:
    before = client.get("/canvas").json()
    result = interaction("Explain how privacy should work in an AI memory system")
    assert any('"mode": "new"' in line for line in result["events"])
    assert any('"transition": "topic-shift"' in line for line in result["events"])
    canvas = client.get("/canvas").json()
    welcome_blocks = [block for block in canvas["blocks"] if block["artifact_id"] == "artifact_no_notes"]
    assert len(welcome_blocks) == len(before["blocks"])
    assert len(canvas["artifacts"]) == 2


def test_follow_up_stream_extends_focused_artifact() -> None:
    canvas = client.get("/canvas").json()
    topic = next(item for item in canvas["artifacts"] if item["id"] != "artifact_no_notes")
    topic_blocks_before = [block for block in canvas["blocks"] if block["artifact_id"] == topic["id"]]
    result = interaction("Add a privacy layer to this", topic["id"], [topic_blocks_before[0]["id"]])
    assert any('"event": "block.started"' in line for line in result["events"])
    assert any('"mode": "extend"' in line for line in result["events"])
    assert any('"transition": "continuation"' in line for line in result["events"])
    canvas = client.get("/canvas").json()
    assert len([block for block in canvas["blocks"] if block["artifact_id"] == topic["id"]]) > len(topic_blocks_before)
    assert len([block for block in canvas["blocks"] if block["artifact_id"] == "artifact_no_notes"]) == 4


def test_modify_replaces_one_block_in_place() -> None:
    canvas = client.get("/canvas").json()
    topic = next(item for item in canvas["artifacts"] if item["id"] != "artifact_no_notes")
    topic_block = next(block for block in canvas["blocks"] if block["artifact_id"] == topic["id"])
    before = len(canvas["blocks"])
    result = interaction("Make this explanation simpler", topic["id"], [topic_block["id"]])
    after_canvas = client.get("/canvas").json()
    assert '"replacing": true' in result["text"]
    assert '"mode": "modify"' in result["text"]
    assert len(after_canvas["blocks"]) == before
    block = next(item for item in after_canvas["blocks"] if item["id"] == topic_block["id"])
    assert "The simple version" in block["html"]


def test_separate_topic_gets_new_region_and_topic_shift() -> None:
    result = interaction("Start a separate topic: plan a two-week Japan trip")
    assert '"mode": "new"' in result["text"]
    assert '"transition": "topic-shift"' in result["text"]
    canvas = client.get("/canvas").json()
    assert len(canvas["artifacts"]) == 3
    original = next(item for item in canvas["artifacts"] if item["id"] == "artifact_no_notes")
    created = next(item for item in canvas["artifacts"] if item["title"] == "Two weeks in Japan")
    assert created["title"] == "Two weeks in Japan"
    assert created["x"] > original["x"] + original["width"]
    assert any(block["artifact_id"] == created["id"] and block["kind"] == "timeline" for block in canvas["blocks"])
