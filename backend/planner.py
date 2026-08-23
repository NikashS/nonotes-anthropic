from __future__ import annotations

import json
import os
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from .database import Artifact, ArtifactBlock, retrieve_artifacts
    from .schemas import BlockItem, CanvasPlan, InteractionRequest, PlanBlock, PlanUpdate
except ImportError:
    from database import Artifact, ArtifactBlock, retrieve_artifacts
    from schemas import BlockItem, CanvasPlan, InteractionRequest, PlanBlock, PlanUpdate


SYSTEM_PROMPT = """You are the generative composition engine for No Notes, an AI interface without chats or threads.
The user works on one persistent spatial canvas. The focused artifact is the default subject of pronouns like this, it, and that.
An artifact with kind `welcome` is orientation, never the user's working topic. Any substantive request while it is focused MUST create a new artifact in a separate region.
For other artifacts, choose modify or extend only when the request refers to the focused work (for example: this, that, it, add, revise, continue, go deeper, or what about). A self-contained request that introduces its own subject creates a new artifact even if something is focused. Choose navigate when the request asks to revisit relevant existing work.
Compose approachable, information-rich answers using a small vocabulary of generative UI blocks. You are not limited to diagrams: combine free text, editorial prose, comparisons, processes, timelines, metrics, callouts, and diagrams when helpful.
Prefer 2-5 blocks. Use boxes only when grouping adds meaning. Keep most prose visually free-standing. Existing stable block IDs may be used in updates; never invent an existing ID.
Styling is controlled by the renderer. Choose block semantics and concise content, not CSS or arbitrary HTML.
The result must stand alone, directly answer the request, and preserve the focused artifact unless the intent is truly separate."""

TOOL = {
    "name": "compose_artifact",
    "description": "Plan targeted edits or additions to a persistent spatial artifact using themed generative UI blocks.",
    "input_schema": CanvasPlan.model_json_schema(),
}


def _compact_context(session: Session, request: InteractionRequest) -> dict:
    artifacts = retrieve_artifacts(session, request.context.canvas_id, request.message, request.context.focused_artifact_id)
    result = []
    for artifact in artifacts:
        blocks = list(session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id).order_by(ArtifactBlock.order)))
        result.append({
            "id": artifact.id,
            "title": artifact.title,
            "summary": artifact.summary,
            "kind": artifact.kind,
            "focused": artifact.id == request.context.focused_artifact_id,
            "blocks": [{"id": block.id, "kind": block.kind, "content": block.content} for block in blocks],
        })
    return {"artifacts": result, "focused_block_ids": request.context.focused_block_ids}


async def anthropic_plan(session: Session, request: InteractionRequest) -> CanvasPlan | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    payload = {
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": "compose_artifact"},
        "messages": [{"role": "user", "content": f"Request: {request.message}\n\nSpatial context:\n{json.dumps(_compact_context(session, request), ensure_ascii=False)}"}],
    }
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=55) as client:
        response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
    for block in response.json().get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "compose_artifact":
            return CanvasPlan.model_validate(block["input"])
    raise ValueError("Claude did not return an artifact composition")


def _title_from_query(query: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9\s-]", "", query).strip().split()
    title = " ".join(words[:7]) or "Untitled thought"
    return title[0].upper() + title[1:]


def _focused_blocks(session: Session, request: InteractionRequest) -> list[ArtifactBlock]:
    ids = request.context.focused_block_ids
    selected = [session.get(ArtifactBlock, block_id) for block_id in ids]
    return [block for block in selected if block]


def _has_continuation_cue(query: str) -> bool:
    patterns = (
        r"\b(this|that|it|these|those)\b",
        r"\b(add|append|include|expand|extend|continue|revise|rewrite|simplify|shorten|change|rename)\b",
        r"\b(go deeper|more on|build on|what about|turn this|visualize this|make this|make it)\b",
        r"^(and|also|but)\b",
    )
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in patterns)


def fallback_plan(session: Session, request: InteractionRequest) -> CanvasPlan:
    query = request.message.strip()
    lower = query.lower()
    focus_id = request.context.focused_artifact_id
    focused = session.get(Artifact, focus_id) if focus_id else None
    focused_blocks = _focused_blocks(session, request)
    all_blocks = list(session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == focus_id).order_by(ArtifactBlock.order))) if focus_id else []

    modify_words = ("simplify", "shorter", "rewrite", "change", "make this", "make it", "rename", "revise")
    new_words = ("new topic", "separate topic", "unrelated", "start separately", "start a new")
    navigate_words = ("take me to", "go to", "show me where", "where is")
    can_continue = bool(focused and focused.kind != "welcome")
    is_modify = bool(can_continue and any(word in lower for word in modify_words))
    is_new = not can_continue or any(word in lower for word in new_words) or not _has_continuation_cue(query)
    new_title = _title_from_query(query)

    if is_modify:
        target = (focused_blocks or [block for block in all_blocks if block.kind in {"hero", "rich_text", "callout"}] or all_blocks)[0]
        return CanvasPlan(
            mode="modify",
            target_artifact_id=focused.id,
            title=focused.title,
            summary=f"Updated in place: {query}",
            updates=[PlanUpdate(
                block_id=target.id,
                title="The simple version",
                body="Your useful work stays on one spatial canvas. Ask naturally; No Notes finds the relevant artifact and changes or extends it where it already lives.",
                variant="accent",
            )],
        )

    if focused and any(word in lower for word in navigate_words):
        return CanvasPlan(mode="navigate", target_artifact_id=focused.id, title=focused.title, summary=focused.summary)

    if "privacy" in lower or "security" in lower:
        blocks = [
            PlanBlock(ref="privacy", kind="diagram", title="A privacy layer around memory", body="Permission checks happen before context reaches generation.", variant="sketch", items=[
                BlockItem(title="Your request", body="Intent and explicit focus"),
                BlockItem(title="Permission filter", body="Identity, scope, and policy"),
                BlockItem(title="Relevant memory", body="Only authorized artifacts"),
                BlockItem(title="Generated answer", body="Sources and uncertainty remain visible"),
            ]),
            PlanBlock(ref="privacy_note", kind="callout", title="Reversible by default", body="Every model-authored change is versioned, attributable, and recoverable.", variant="ink"),
        ]
        summary = "Permission-filtered retrieval with legible, reversible memory."
    elif is_new and ("japan" in lower or "trip" in lower or "travel" in lower):
        new_title = "Two weeks in Japan"
        blocks = [
            PlanBlock(ref="trip_hero", kind="hero", eyebrow="A new topic", title="Two weeks in Japan", body="A paced route that gives Tokyo, Kyoto, and the mountains enough room to feel distinct.", variant="plain"),
            PlanBlock(ref="trip_timeline", kind="timeline", title="A balanced route", variant="sketch", items=[
                BlockItem(title="Days 1–4 · Tokyo", body="Neighborhoods, food, and one flexible day trip."),
                BlockItem(title="Days 5–6 · Japanese Alps", body="Slow down in a mountain town or onsen."),
                BlockItem(title="Days 7–11 · Kyoto", body="Temples early, quieter neighborhoods later."),
                BlockItem(title="Days 12–14 · Osaka", body="Street food, design, and an easy departure."),
            ]),
            PlanBlock(ref="trip_note", kind="callout", title="Keep one day unplanned", body="The best itinerary leaves room to follow weather, energy, and discoveries.", variant="accent"),
        ]
        summary = "A balanced two-week Japan route with room for discovery."
    else:
        blocks = [
            PlanBlock(ref="answer", kind="rich_text", title=_title_from_query(query), body="No Notes stores outcomes as durable artifacts. Each request combines explicit focus with retrieval, then updates the existing composition or adds the most useful material nearby.", variant="plain"),
            PlanBlock(ref="continuity", kind="process", title="Continuity before creation", variant="sketch", items=[
                BlockItem(title="Resolve focus", body="What is the user referring to?"),
                BlockItem(title="Retrieve context", body="What is the smallest useful memory?"),
                BlockItem(title="Render deliberately", body="Modify, extend, navigate, or create."),
            ]),
        ]
        summary = "Focused retrieval followed by deliberate spatial composition."

    return CanvasPlan(
        mode="new" if is_new else "extend",
        target_artifact_id=None if is_new else focused.id,
        title=new_title if is_new else focused.title,
        summary=summary,
        layout="editorial",
        blocks=blocks,
    )


async def make_plan(session: Session, request: InteractionRequest) -> tuple[CanvasPlan, str]:
    try:
        plan = await anthropic_plan(session, request)
        if plan:
            focused = session.get(Artifact, request.context.focused_artifact_id) if request.context.focused_artifact_id else None
            # Keep the product introduction pristine even if a model mistakes
            # visual focus for conversational continuity.
            if focused and focused.kind == "welcome" and plan.mode != "new":
                return fallback_plan(session, request), "local"
            return plan, "claude"
    except (httpx.HTTPError, ValueError):
        if os.getenv("NONOTES_STRICT_MODEL") == "1":
            raise
    return fallback_plan(session, request), "local"
