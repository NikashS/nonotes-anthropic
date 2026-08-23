from __future__ import annotations

import json
import os
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from .database import Artifact, SceneElement, retrieve_artifacts
    from .schemas import CanvasPlan, InteractionRequest, PlanConnection, PlanElement, PlanUpdate
except ImportError:  # Vercel Services imports the entrypoint as a top-level module.
    from database import Artifact, SceneElement, retrieve_artifacts
    from schemas import CanvasPlan, InteractionRequest, PlanConnection, PlanElement, PlanUpdate


SYSTEM_PROMPT = """You are the spatial composition engine for No Notes, an AI interface without chats or threads.
The user works on one persistent infinite canvas. The focused artifact is the default subject of pronouns like this, it, and that.
Choose modify when changing focused content in place, extend when adding to it nearby, navigate when relevant work already exists elsewhere, and new only when the intent is genuinely separate.
Never recreate an entire focused composition when a targeted update or a few additions are sufficient.
Compose concise, useful answers from text chunks, rectangles, ellipses, and labeled arrows on one flat plane.
Text elements are for prose, headings, lists, and caveats. Shape elements are semantic diagram nodes. Prefer 2-6 elements total.
Use Markdown in element content. Existing element IDs may be used in updates, relative_to, and connector refs. Do not invent existing IDs.
The visible result must stand alone and directly answer the user's request."""


TOOL = {
    "name": "render_canvas",
    "description": "Create a validated plan of targeted edits and additions on the persistent No Notes canvas. Use existing stable element IDs for updates. New elements use short local refs which connectors can reference.",
    "input_schema": CanvasPlan.model_json_schema(),
}


def _compact_context(session: Session, request: InteractionRequest) -> dict:
    artifacts = retrieve_artifacts(
        session,
        request.context.canvas_id,
        request.message,
        request.context.focused_artifact_id,
    )
    result = []
    for artifact in artifacts:
        elements = list(session.scalars(select(SceneElement).where(SceneElement.artifact_id == artifact.id)))
        result.append({
            "id": artifact.id,
            "title": artifact.title,
            "summary": artifact.summary,
            "focused": artifact.id == request.context.focused_artifact_id,
            "elements": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "shape": item.shape,
                    "content": item.content[:900],
                    "position": {"x": item.x, "y": item.y},
                }
                for item in elements
            ],
        })
    return {"artifacts": result, "selected_element_ids": request.context.selected_element_ids}


async def anthropic_plan(session: Session, request: InteractionRequest) -> CanvasPlan | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    payload = {
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": "render_canvas"},
        "messages": [{
            "role": "user",
            "content": f"Request: {request.message}\n\nCanvas context:\n{json.dumps(_compact_context(session, request), ensure_ascii=False)}",
        }],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=55) as client:
        response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
    for block in response.json().get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "render_canvas":
            return CanvasPlan.model_validate(block["input"])
    raise ValueError("Claude did not return a canvas plan")


def fallback_plan(session: Session, request: InteractionRequest) -> CanvasPlan:
    query = request.message.strip()
    lower = query.lower()
    focus_id = request.context.focused_artifact_id
    focused = session.get(Artifact, focus_id) if focus_id else None
    selected = [session.get(SceneElement, item) for item in request.context.selected_element_ids]
    selected = [item for item in selected if item]
    focus_elements = list(session.scalars(select(SceneElement).where(SceneElement.artifact_id == focus_id))) if focus_id else []

    modify_words = ("simplify", "shorter", "rewrite", "change", "make this", "make it", "rename")
    navigate_words = ("take me to", "go to", "show me", "where is")
    is_modify = bool(focused and any(word in lower for word in modify_words))
    is_navigate = any(word in lower for word in navigate_words)

    if is_modify:
        target = (selected or [item for item in focus_elements if item.kind == "text"] or focus_elements)[0]
        return CanvasPlan(
            mode="modify",
            target_artifact_id=focused.id,
            title=focused.title,
            summary=f"Updated in place: {query}",
            updates=[PlanUpdate(
                element_id=target.id,
                content=f"## {focused.title}\n{query.capitalize()}\n\nThe essential idea: your work remains on one canvas, and every follow-up changes or extends the focused material instead of starting over.",
            )],
        )

    if is_navigate and focused:
        return CanvasPlan(
            mode="navigate",
            target_artifact_id=focused.id,
            title=focused.title,
            summary=focused.summary,
        )

    mode = "extend" if focused else "new"
    title = _title_from_query(query)
    target_id = focused.id if focused else None
    anchor = selected[0].id if selected else (focus_elements[-1].id if focus_elements else None)
    if "privacy" in lower or "security" in lower:
        elements = [
            PlanElement(ref="privacy", kind="shape", shape="rectangle", content="### Privacy boundary\nPermission-filter context before retrieval and generation.", relative_to=anchor, direction="right", width=300, height=150),
            PlanElement(ref="audit", kind="shape", shape="ellipse", content="### Legible memory\nShow sources, uncertainty, and every reversible change.", relative_to="privacy", direction="below", width=300, height=170),
        ]
        connections = [PlanConnection(source_ref=anchor or "privacy", target_ref="privacy", label="filters"), PlanConnection(source_ref="privacy", target_ref="audit", label="records")]
        summary = "A privacy layer built around permission-filtered retrieval and auditable memory."
    else:
        elements = [
            PlanElement(ref="answer", kind="text", content=f"## {title}\n{_answer_for(query)}", relative_to=anchor, direction="right", width=430, height=180),
            PlanElement(ref="principle", kind="shape", shape="rectangle", content="### Continuity first\nReuse focused work, retrieve related artifacts, and create a new region only for genuinely separate intent.", relative_to="answer", direction="below", width=330, height=155),
        ]
        connections = [PlanConnection(source_ref="answer", target_ref="principle", label="guides")]
        summary = _answer_for(query)

    return CanvasPlan(mode=mode, target_artifact_id=target_id, title=title, summary=summary, elements=elements, connections=connections)


def _title_from_query(query: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9\s-]", "", query).strip().split()
    title = " ".join(words[:7]) or "Untitled thought"
    return title[0].upper() + title[1:]


def _answer_for(query: str) -> str:
    if "how" in query.lower() and "no notes" in query.lower():
        return "No Notes stores useful outcomes as durable artifacts. Each request combines explicit focus with retrieval, then modifies existing work, adds nearby material, or navigates to a related region."
    return f"This builds on the current knowledge space in response to: **{query}**. The result stays addressable, editable, and connected to its source context."


async def make_plan(session: Session, request: InteractionRequest) -> tuple[CanvasPlan, str]:
    try:
        plan = await anthropic_plan(session, request)
        if plan:
            return plan, "claude"
    except (httpx.HTTPError, ValueError):
        if os.getenv("NONOTES_STRICT_MODEL") == "1":
            raise
    return fallback_plan(session, request), "local"
