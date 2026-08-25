from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["DATABASE_URL"] = f"sqlite:////tmp/nonotes-test-{uuid4().hex}.db"

from backend.database import Artifact, ArtifactBlock, ArtifactRegion, engine
from backend.main import _compile_fragments, app
from backend import planner
from backend.planner import _semantic_plan, _validate_plan_input
from backend.schemas import BlockItem, InteractionRequest, OutlineBlock

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


def test_process_renderer_never_places_content_in_connector_columns() -> None:
    items = [BlockItem(title=f"Step {index}", body="Readable content") for index in range(1, 8)]
    html = "".join(_compile_fragments("process", "Seven steps", "", "", items))
    assert html.count("<div>") == 7
    assert "<i>" not in html
    assert 'data-count="7"' in html


def test_all_outline_blocks_are_filled_with_one_model_call(monkeypatch) -> None:
    calls = 0

    async def fake_call_tool(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"blocks": [
            {"ref": "intro", "content": {"title": "Fast intro", "body": "One pass."}},
            {"ref": "steps", "content": {"title": "Flow", "items": [
                {"title": "One", "body": "First"},
                {"title": "Two", "body": "Second"},
                {"title": "Three", "body": "Ignored"},
            ]}},
        ]}

    monkeypatch.setattr(planner, "_call_tool", fake_call_tool)
    slots = [
        (OutlineBlock(ref="intro", kind="rich_text"), None),
        (OutlineBlock(ref="steps", kind="process", item_count=2), None),
    ]
    result = asyncio.run(planner.fill_outline_blocks(
        InteractionRequest(message="Explain a flow"), "Flow", "A useful flow", slots, "claude", {},
    ))

    assert calls == 1
    assert set(result) == {"intro", "steps"}
    assert len(result["steps"].items) == 2


def test_provisional_sql_outline_does_not_wait_for_a_model(monkeypatch) -> None:
    async def model_must_not_run(*args, **kwargs):
        raise AssertionError("outline planning must not call Anthropic")

    monkeypatch.setattr(planner, "_call_tool", model_must_not_run)
    request = InteractionRequest(message="What are some good options for SQL?")
    with Session(engine) as session:
        outline, selected_planner, fallbacks, retrieval = asyncio.run(planner.make_outline(session, request))

    assert selected_planner == "claude"
    assert [block.kind for block in outline.blocks] == ["rich_text", "comparison", "callout"]
    assert set(fallbacks) == {block.ref for block in outline.blocks}
    assert all("No Notes stores outcomes" not in block.body for block in fallbacks.values())


def test_explanations_always_reserve_a_visual_block() -> None:
    for message in (
        "Explain Newton's three laws of motion",
        "Why do leaves change color?",
        "Describe how a bill becomes law",
    ):
        with Session(engine) as session:
            plan = _semantic_plan(session, InteractionRequest(message=message), {"artifacts": []})
        assert any(block.kind in {"diagram", "process", "comparison", "timeline", "metrics"} for block in plan.blocks)

    with Session(engine) as session:
        newton = _semantic_plan(
            session, InteractionRequest(message="Explain Newton's three laws of motion"), {"artifacts": []},
        )
    visual = next(block for block in newton.blocks if block.kind == "comparison")
    assert [item.label for item in visual.items] == ["Law 1", "Law 2", "Law 3"]


def test_renderer_removes_unsupported_markdown_markers() -> None:
    html = "".join(_compile_fragments("rich_text", "Core", "", "**Law 1:** use `F = ma`", []))
    assert "**" not in html
    assert "`" not in html
    assert "Law 1:" in html


def test_first_question_leaves_welcome_and_uses_a_new_region() -> None:
    before = client.get("/canvas").json()
    result = interaction("Explain how privacy should work in an AI memory system")
    assert any('"mode": "new"' in line for line in result["events"])
    assert any('"transition": "topic-shift"' in line for line in result["events"])
    outlined = next(index for index, line in enumerate(result["events"]) if '"event": "block.outlined"' in line)
    outline_committed = next(index for index, line in enumerate(result["events"]) if '"event": "outline.committed"' in line)
    content_started = next(index for index, line in enumerate(result["events"]) if '"event": "block.started"' in line)
    assert outlined < outline_committed < content_started
    assert '"_outline"' in result["events"][outlined]
    canvas = client.get("/canvas").json()
    welcome_blocks = [block for block in canvas["blocks"] if block["artifact_id"] == "artifact_no_notes"]
    assert len(welcome_blocks) == len(before["blocks"])
    assert len(canvas["artifacts"]) == 2


def test_follow_up_stream_extends_focused_artifact() -> None:
    canvas = client.get("/canvas").json()
    topic = next(item for item in canvas["artifacts"] if item["id"] != "artifact_no_notes")
    durable_summary = topic["summary"]
    topic_blocks_before = [block for block in canvas["blocks"] if block["artifact_id"] == topic["id"]]
    result = interaction("Add a privacy layer to this", topic["id"], [topic_blocks_before[0]["id"]])
    assert any('"event": "block.started"' in line for line in result["events"])
    assert any('"mode": "extend"' in line for line in result["events"])
    assert any('"transition": "continuation"' in line for line in result["events"])
    canvas = client.get("/canvas").json()
    updated_topic = next(item for item in canvas["artifacts"] if item["id"] == topic["id"])
    assert updated_topic["summary"] == durable_summary
    assert len([block for block in canvas["blocks"] if block["artifact_id"] == topic["id"]]) > len(topic_blocks_before)
    assert len([block for block in canvas["blocks"] if block["artifact_id"] == "artifact_no_notes"]) == 4


def test_related_follow_up_is_inserted_after_the_relevant_block() -> None:
    artifact_id = f"artifact_anchor_{uuid4().hex[:8]}"
    hero_id = f"block_hero_{uuid4().hex[:8]}"
    light_clock_id = f"block_light_{uuid4().hex[:8]}"
    orbital_id = f"block_orbit_{uuid4().hex[:8]}"
    with Session(engine) as session:
        session.add(Artifact(
            id=artifact_id,
            canvas_id="main",
            title="Why Time Slows Near the Speed of Light",
            summary="A visual explanation of the light-clock thought experiment and relativity.",
        ))
        session.add(ArtifactRegion(artifact_id=artifact_id))
        session.add_all([
            ArtifactBlock(id=hero_id, artifact_id=artifact_id, kind="hero", order=0, content={"title": "Time dilation"}),
            ArtifactBlock(id=light_clock_id, artifact_id=artifact_id, kind="diagram", order=1, content={"title": "The Light-Clock Thought Experiment"}),
            ArtifactBlock(id=orbital_id, artifact_id=artifact_id, kind="rich_text", order=2, content={"title": "Falling Around the Earth"}),
        ])
        session.commit()

    result = interaction("Who discovered the light-clock thought experiment?", artifact_id)
    reordered_event = next(index for index, line in enumerate(result["events"]) if '"event": "blocks.reordered"' in line)
    outlined_event = next(index for index, line in enumerate(result["events"]) if '"event": "block.outlined"' in line)
    assert reordered_event < outlined_event
    committed = next(json.loads(line) for line in result["events"] if '"event": "outline.committed"' in line)
    assert committed["payload"]["insert_after_block_id"] == light_clock_id

    canvas = client.get("/canvas").json()
    ordered = sorted(
        (block for block in canvas["blocks"] if block["artifact_id"] == artifact_id),
        key=lambda block: block["order"],
    )
    inserted_ids = committed["payload"]["block_ids"]
    assert [block["id"] for block in ordered][1:2 + len(inserted_ids)] == [light_clock_id, *inserted_ids]
    assert ordered[-1]["id"] == orbital_id


def test_named_topic_beats_unrelated_focused_artifact() -> None:
    physics_id = f"artifact_physics_{uuid4().hex[:8]}"
    travel_id = f"artifact_portugal_{uuid4().hex[:8]}"
    portugal_block_id = f"block_portugal_{uuid4().hex[:8]}"
    request = InteractionRequest.model_validate({
        "message": "Add Nazaré to the Portugal plan",
        "context": {"focused_artifact_id": physics_id},
    })
    retrieval = {
        "artifacts": [
            {"id": travel_id, "kind": "composition", "retrieval": {"score": 0.72, "semantic": 0.8, "lexical": 0.22}},
            {"id": physics_id, "kind": "composition", "retrieval": {"score": 0.12, "semantic": 0.08, "lexical": 0.0}},
        ],
    }
    with Session(engine) as session:
        session.add_all([
            Artifact(id=physics_id, canvas_id="main", title="Time Dilation", summary="Special relativity"),
            Artifact(id=travel_id, canvas_id="main", title="Portugal at a Gentle Pace", summary="A Portugal itinerary"),
            ArtifactBlock(id=f"block_physics_{uuid4().hex[:8]}", artifact_id=physics_id, kind="hero", order=0, content={"title": "Time Dilation"}),
            ArtifactBlock(id=portugal_block_id, artifact_id=travel_id, kind="hero", order=0, content={"title": "Portugal at a Gentle Pace"}),
        ])
        session.flush()
        plan = _semantic_plan(session, request, retrieval)

    assert plan.mode == "extend"
    assert plan.target_artifact_id == travel_id
    assert plan.insert_after_block_id == portugal_block_id


def test_unrelated_focus_does_not_create_a_continuation() -> None:
    physics_id = f"artifact_focus_{uuid4().hex[:8]}"
    request = InteractionRequest.model_validate({
        "message": "Explain how sourdough fermentation works",
        "context": {"focused_artifact_id": physics_id},
    })
    retrieval = {
        "artifacts": [{
            "id": physics_id,
            "kind": "composition",
            "retrieval": {"score": 0.08, "semantic": 0.09, "lexical": 0.0},
        }],
    }
    with Session(engine) as session:
        session.add(Artifact(id=physics_id, canvas_id="main", title="Time Dilation", summary="Special relativity"))
        session.flush()
        plan = _semantic_plan(session, request, retrieval)

    assert plan.mode == "new"
    assert plan.target_artifact_id is None


def test_named_topic_can_bootstrap_an_artifact_with_a_missing_vector() -> None:
    physics_id = f"artifact_vectorless_{uuid4().hex[:8]}"
    unrelated_id = f"artifact_unrelated_{uuid4().hex[:8]}"
    request = InteractionRequest.model_validate({
        "message": "Compare special relativity time dilation evidence from atomic clocks and muons",
        "context": {"focused_artifact_id": unrelated_id},
    })
    retrieval = {
        "artifacts": [
            {"id": physics_id, "kind": "composition", "retrieval": {"score": 0.28, "semantic": 0.0, "lexical": 0.21}},
            {"id": unrelated_id, "kind": "composition", "retrieval": {"score": 0.15, "semantic": 0.76, "lexical": 0.0}},
        ],
    }
    with Session(engine) as session:
        session.add_all([
            Artifact(id=physics_id, canvas_id="main", title="Time Dilation", summary="Special relativity and experimental evidence"),
            Artifact(id=unrelated_id, canvas_id="main", title="Redis", summary="An in-memory database"),
        ])
        session.flush()
        plan = _semantic_plan(session, request, retrieval)

    assert plan.mode == "extend"
    assert plan.target_artifact_id == physics_id


def test_cross_topic_embedding_baseline_starts_a_new_region() -> None:
    physics_id = f"artifact_threshold_{uuid4().hex[:8]}"
    request = InteractionRequest.model_validate({
        "message": "Visualize when a relational database beats a document or graph database",
        "context": {"focused_artifact_id": physics_id},
    })
    retrieval = {
        "artifacts": [{
            "id": physics_id,
            "kind": "composition",
            "retrieval": {"score": 0.1446, "semantic": 0.7603, "lexical": 0.0},
        }],
    }
    with Session(engine) as session:
        session.add(Artifact(
            id=physics_id,
            canvas_id="main",
            title="Why Time Slows Near the Speed of Light",
            summary="Special relativity and the light-clock thought experiment",
        ))
        session.flush()
        plan = _semantic_plan(session, request, retrieval)

    assert plan.mode == "new"
    assert plan.target_artifact_id is None


def test_high_confidence_semantic_match_extends_existing_region() -> None:
    physics_id = f"artifact_semantic_{uuid4().hex[:8]}"
    request = InteractionRequest.model_validate({
        "message": "Explain the twin paradox visually",
        "context": {},
    })
    retrieval = {
        "artifacts": [{
            "id": physics_id,
            "kind": "composition",
            "retrieval": {"score": 0.3197, "semantic": 0.8332, "lexical": 0.0},
        }],
    }
    with Session(engine) as session:
        session.add(Artifact(
            id=physics_id,
            canvas_id="main",
            title="Why Time Slows Near the Speed of Light",
            summary="Special relativity and the light-clock thought experiment",
        ))
        session.flush()
        plan = _semantic_plan(session, request, retrieval)

    assert plan.mode == "extend"
    assert plan.target_artifact_id == physics_id


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
    before = client.get("/canvas").json()
    result = interaction("Start a separate topic: plan a two-week Japan trip")
    assert '"mode": "new"' in result["text"]
    assert '"transition": "topic-shift"' in result["text"]
    canvas = client.get("/canvas").json()
    assert len(canvas["artifacts"]) == len(before["artifacts"]) + 1
    original = next(item for item in canvas["artifacts"] if item["id"] == "artifact_no_notes")
    created = next(item for item in canvas["artifacts"] if item["title"] == "Two weeks in Japan")
    assert created["title"] == "Two weeks in Japan"
    assert created["x"] > original["x"] + original["width"]
    assert any(block["artifact_id"] == created["id"] and block["kind"] == "timeline" for block in canvas["blocks"])
