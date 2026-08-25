from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from .database import Artifact, ArtifactBlock, retrieve_artifacts
    from .embeddings import generate_embedding
    from .schemas import (
        BlockContent, BlockItem, CanvasOutline, CanvasPlan, GeneratedBlockBatch, InteractionRequest,
        OutlineBlock, OutlineUpdate, PlanBlock, PlanUpdate,
    )
except ImportError:
    from database import Artifact, ArtifactBlock, retrieve_artifacts
    from embeddings import generate_embedding
    from schemas import (
        BlockContent, BlockItem, CanvasOutline, CanvasPlan, GeneratedBlockBatch, InteractionRequest,
        OutlineBlock, OutlineUpdate, PlanBlock, PlanUpdate,
    )


CONTENT_TOOL = {
    "name": "fill_blocks",
    "description": "Write concise content for every predefined visual block in one response.",
    "input_schema": GeneratedBlockBatch.model_json_schema(),
    "eager_input_streaming": True,
}

logger = logging.getLogger(__name__)


def _log_timing(stage: str, started: float, **details: object) -> None:
    logger.info(json.dumps({
        "level": "info",
        "message": "latency.stage",
        "stage": stage,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        **details,
    }))


async def _compact_context(session: Session, request: InteractionRequest) -> dict:
    retrieval_query = request.message
    if _has_deictic_reference(request.message) and request.context.focused_artifact_id:
        focused = session.get(Artifact, request.context.focused_artifact_id)
        if focused and focused.kind != "welcome":
            focused_blocks = [
                session.get(ArtifactBlock, block_id)
                for block_id in request.context.focused_block_ids
            ]
            focus_text = [focused.title, focused.summary]
            for block in focused_blocks:
                if block and block.artifact_id == focused.id:
                    content = block.content or {}
                    focus_text.extend([str(content.get("title", "")), str(content.get("body", ""))])
            retrieval_query = f"{request.message}\nContext referred to: " + "\n".join(part for part in focus_text if part)

    embedding = None
    if session.bind and session.bind.dialect.name == "postgresql":
        started = time.perf_counter()
        embedding = await generate_embedding(retrieval_query)
        _log_timing("retrieval.embedding", started, available=bool(embedding))
    started = time.perf_counter()
    candidates = retrieve_artifacts(
        session, request.context.canvas_id, retrieval_query,
        request.context.focused_artifact_id, embedding,
    )
    _log_timing("retrieval.database", started, candidate_count=len(candidates))
    result = []
    for candidate in candidates:
        artifact = candidate.artifact
        blocks = list(session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id).order_by(ArtifactBlock.order)))
        result.append({
            "id": artifact.id,
            "title": artifact.title,
            "summary": artifact.summary,
            "kind": artifact.kind,
            "focused": artifact.id == request.context.focused_artifact_id,
            "retrieval": {
                "score": round(candidate.score, 4),
                "semantic": round(candidate.semantic_score, 4),
                "lexical": round(candidate.lexical_score, 4),
                "focus": round(candidate.focus_score, 4),
            },
            "blocks": [{"id": block.id, "kind": block.kind, "content": block.content} for block in blocks],
        })
    return {
        "retrieval_method": "semantic_hybrid" if embedding else "lexical_fallback",
        "retrieval_query": retrieval_query,
        "artifacts": result,
        "focused_block_ids": request.context.focused_block_ids,
    }


def _validate_plan_input(raw: dict) -> CanvasPlan:
    """Accept the compact pipe-delimited rows used by older persisted blocks."""
    for collection in (raw.get("blocks", []), raw.get("updates", [])):
        for block in collection:
            items = block.get("items", [])
            block["items"] = [
                {"title": parts[0].strip(), "body": " · ".join(part.strip() for part in parts[1:])}
                if isinstance(item, str) and (parts := item.split("|"))
                else item
                for item in items
            ]
    return CanvasPlan.model_validate(raw)


async def _call_tool(system: str, tool: dict, prompt: str, max_tokens: int, timeout_seconds: float) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Anthropic is not configured")
    payload = {
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "max_tokens": max_tokens,
        "system": system,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": tool["name"]},
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    started = time.perf_counter()
    try:
        tool_index: int | None = None
        partial_json: list[str] = []
        initial_input: dict | None = None
        timeout = httpx.Timeout(10, connect=5, write=5, pool=5)
        async with asyncio.timeout(timeout_seconds):
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", "https://api.anthropic.com/v1/messages", headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = json.loads(line[6:])
                        if data.get("type") == "error":
                            raise ValueError(data.get("error", {}).get("message", "Anthropic stream failed"))
                        if data.get("type") == "content_block_start":
                            block = data.get("content_block", {})
                            if block.get("type") == "tool_use" and block.get("name") == tool["name"]:
                                tool_index = data.get("index")
                                if isinstance(block.get("input"), dict) and block["input"]:
                                    initial_input = block["input"]
                        elif data.get("type") == "content_block_delta" and data.get("index") == tool_index:
                            delta = data.get("delta", {})
                            if delta.get("type") == "input_json_delta":
                                partial_json.append(delta.get("partial_json", ""))
        if partial_json:
            return json.loads("".join(partial_json))
        if initial_input is not None:
            return initial_input
        raise ValueError(f"Claude did not call {tool['name']}")
    finally:
        _log_timing(f"anthropic.{tool['name']}", started, max_tokens=max_tokens)


def _outline_from_plan(session: Session, plan: CanvasPlan) -> tuple[CanvasOutline, dict[str, PlanBlock]]:
    fallback_content: dict[str, PlanBlock] = {}
    blocks: list[OutlineBlock] = []
    updates: list[OutlineUpdate] = []
    for block in plan.blocks:
        size = "large" if block.kind in {"hero", "diagram", "timeline"} else "compact" if block.kind == "callout" else "standard"
        blocks.append(OutlineBlock(
            ref=block.ref, kind=block.kind, title_hint=block.title, variant=block.variant,
            item_count=len(block.items), size=size,
        ))
        fallback_content[block.ref] = block
    for index, update in enumerate(plan.updates):
        current = session.get(ArtifactBlock, update.block_id)
        if not current:
            continue
        ref = f"update_{index}"
        updates.append(OutlineUpdate(
            ref=ref, block_id=update.block_id, kind=current.kind,
            title_hint=update.title or (current.content or {}).get("title", ""),
            variant=update.variant or current.variant,
            item_count=len(update.items or (current.content or {}).get("items", [])),
            size="large" if current.kind in {"hero", "diagram", "timeline"} else "compact" if current.kind == "callout" else "standard",
        ))
        fallback_content[ref] = PlanBlock(
            ref=ref, kind=current.kind, title=update.title, eyebrow=update.eyebrow,
            body=update.body, items=update.items, variant=update.variant or current.variant,
        )
    return CanvasOutline(
        mode=plan.mode, title=plan.title, summary=plan.summary,
        target_artifact_id=plan.target_artifact_id,
        insert_after_block_id=plan.insert_after_block_id,
        layout=plan.layout,
        blocks=blocks, updates=updates,
    ), fallback_content


async def make_outline(session: Session, request: InteractionRequest) -> tuple[CanvasOutline, str, dict[str, PlanBlock], dict]:
    retrieval = await _compact_context(session, request)
    outline, fallback_content = _outline_from_plan(session, _semantic_plan(session, request, retrieval))
    return outline, "claude", fallback_content, retrieval


async def fill_outline_blocks(
    request: InteractionRequest,
    artifact_title: str,
    artifact_summary: str,
    slots: list[tuple[OutlineBlock | OutlineUpdate, dict | None]],
    planner: str,
    fallbacks: dict[str, PlanBlock],
) -> dict[str, PlanBlock]:
    if not slots:
        return {}
    if planner == "local":
        return {slot.ref: fallbacks[slot.ref] for slot, _ in slots if slot.ref in fallbacks}
    system = """You write every section of one hand-drawn visual explanation in a single pass. Respect each predefined block kind, reference, and footprint exactly.
Return one result for every supplied ref and no others, in the same order. Return the requested number of items so the layout does not shift. Make the sections complementary rather than repetitive. Be concrete, explanatory, and concise. Avoid generic introductions and UI language.
For diagrams and processes, each item is a node or step. For comparisons, each item is a meaningful dimension or option. For timelines, each item is a stage. Body text should usually stay under 80 words and item bodies under 24 words."""
    def prompt_for(selected: list[tuple[OutlineBlock | OutlineUpdate, dict | None]]) -> str:
        return json.dumps({
            "request": request.message,
            "artifact": {"title": artifact_title, "summary": artifact_summary},
            "slots": [
                {
                    "outline": slot.model_dump(),
                    "existing_content": existing,
                    "requirements": {"exact_item_count": slot.item_count},
                }
                for slot, existing in selected
            ],
        }, ensure_ascii=False)

    try:
        raw = await _call_tool(system, CONTENT_TOOL, prompt_for(slots), min(1800, 420 + len(slots) * 340), 30)
        batch = GeneratedBlockBatch.model_validate(raw)
        generated = {item.ref: item.content for item in batch.blocks}
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning("Anthropic batch generation unavailable: %s", type(exc).__name__)
        generated = {}
        # A smaller retry still produces one useful answer if a large visual
        # composition exceeds its budget. The remaining blocks retain their
        # query-specific fallback content instead of product boilerplate.
        try:
            raw = await _call_tool(system, CONTENT_TOOL, prompt_for(slots[:1]), 650, 10)
            batch = GeneratedBlockBatch.model_validate(raw)
            generated = {item.ref: item.content for item in batch.blocks}
            logger.info(json.dumps({"level": "info", "message": "generation.recovered", "strategy": "primary_block_retry"}))
        except (httpx.HTTPError, TimeoutError, ValueError) as retry_exc:
            logger.warning("Anthropic primary block retry unavailable: %s", type(retry_exc).__name__)

    result: dict[str, PlanBlock] = {}
    for slot, _ in slots:
        content = generated.get(slot.ref)
        if content:
            content.items = content.items[:slot.item_count] if slot.item_count else []
            result[slot.ref] = PlanBlock(
                ref=slot.ref, kind=slot.kind, title=content.title or slot.title_hint,
                eyebrow=content.eyebrow, body=content.body, items=content.items, variant=slot.variant,
            )
        elif slot.ref in fallbacks:
            result[slot.ref] = fallbacks[slot.ref]
        else:
            result[slot.ref] = PlanBlock(
                ref=slot.ref, kind=slot.kind, title=slot.title_hint,
                body=f"A concise answer to “{request.message}” is not available yet.", variant=slot.variant,
            )
    return result


def _title_from_query(query: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9\s-]", "", query).strip().split()
    title = " ".join(words[:7]) or "Untitled thought"
    return title[0].upper() + title[1:]


def _has_deictic_reference(query: str) -> bool:
    """True when the user explicitly points at the currently focused work."""
    return bool(
        re.search(r"\b(this|that|it|these|those)\b", query, re.IGNORECASE)
        or re.search(r"^(and|also|but)\b", query, re.IGNORECASE)
    )


_ANCHOR_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "can", "could", "did", "does", "for",
    "from", "have", "how", "into", "more", "that", "the", "their", "this", "what", "when",
    "where", "which", "who", "with", "would", "you", "your",
}


def _anchor_terms(value: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]+", value.lower())
        if len(word) > 2 and word not in _ANCHOR_STOP_WORDS
    }


def _select_anchor_block(query: str, blocks: list[ArtifactBlock], focused_block_ids: list[str]) -> ArtifactBlock | None:
    """Pick the section a follow-up is actually about, without another model call."""
    query_terms = _anchor_terms(query)
    focused = set(focused_block_ids)
    best: ArtifactBlock | None = None
    best_score = 0.0

    for block in blocks:
        content = block.content or {}
        title_terms = _anchor_terms(f"{content.get('eyebrow', '')} {content.get('title', '')}")
        body_terms = _anchor_terms(str(content.get("body", "")))
        item_terms: set[str] = set()
        for item in content.get("items", []):
            if isinstance(item, dict):
                item_terms |= _anchor_terms(f"{item.get('label', '')} {item.get('title', '')} {item.get('body', '')}")

        score = (
            len(query_terms & title_terms) * 3.0
            + len(query_terms & body_terms)
            + len(query_terms & item_terms) * 1.25
            + (0.75 if block.id in focused else 0.0)
        )
        if score > best_score or (score == best_score and best is not None and block.order > best.order):
            best = block
            best_score = score

    if best_score > 0:
        return best
    return next((block for block in blocks if block.id in focused), None)


def _semantic_plan(session: Session, request: InteractionRequest, retrieval: dict) -> CanvasPlan:
    """Create a fast spatial contract from vector retrieval and explicit intent.

    The model writes the answer, but it is not allowed to block the first useful
    canvas update. Semantic similarity selects continuity; lightweight intent
    cues only resolve explicit new/modify/navigation requests.
    """
    query = request.message.strip()
    lower = query.lower()
    candidates = [item for item in retrieval.get("artifacts", []) if item.get("kind") != "welcome"]
    best = candidates[0] if candidates else None
    best_scores = (best or {}).get("retrieval", {})
    strong_match = bool(best and (
        float(best_scores.get("semantic", 0)) >= 0.76
        or float(best_scores.get("score", 0)) >= 0.18
        or float(best_scores.get("lexical", 0)) >= 0.18
    ))

    explicit_new = any(phrase in lower for phrase in (
        "new topic", "separate topic", "unrelated", "start separately", "start a new",
    ))
    modify = any(word in lower for word in (
        "simplify", "shorter", "rewrite", "change", "make this", "make it", "rename", "revise",
    ))
    navigate = any(word in lower for word in ("take me to", "go to", "show me where", "where is"))

    target = None
    if not explicit_new and strong_match:
        target = session.get(Artifact, best["id"])

    if navigate and target:
        return CanvasPlan(mode="navigate", target_artifact_id=target.id, title=target.title, summary=target.summary)

    if modify and target:
        blocks = list(session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == target.id).order_by(ArtifactBlock.order)))
        preferred = [session.get(ArtifactBlock, block_id) for block_id in request.context.focused_block_ids]
        block = next((item for item in preferred if item and item.artifact_id == target.id), None)
        block = block or next((item for item in blocks if item.kind in {"hero", "rich_text", "callout"}), None)
        block = block or (blocks[0] if blocks else None)
        if block:
            content = block.content or {}
            return CanvasPlan(
                mode="modify", target_artifact_id=target.id, title=target.title,
                summary=f"Updated in place for: {query}",
                updates=[PlanUpdate(
                    block_id=block.id,
                    title="The simple version" if "simpl" in lower else str(content.get("title", "")),
                    eyebrow=str(content.get("eyebrow", "")),
                    body=str(content.get("body", "")),
                    items=[BlockItem.model_validate(item) for item in content.get("items", []) if isinstance(item, dict)],
                    variant=block.variant,
                )],
            )

    mode = "extend" if target else "new"
    target_blocks = list(session.scalars(
        select(ArtifactBlock).where(ArtifactBlock.artifact_id == target.id).order_by(ArtifactBlock.order)
    )) if target else []
    anchor = _select_anchor_block(query, target_blocks, request.context.focused_block_ids)
    title = target.title if target else _title_from_query(query)
    if not target and "japan" in lower and any(word in lower for word in ("trip", "travel", "itinerary")):
        if "ten" in lower or "10" in lower:
            title = "Ten days in Japan"
        elif "two-week" in lower or "two week" in lower or "two weeks" in lower:
            title = "Two weeks in Japan"
        else:
            title = "Japan itinerary"

    if any(word in lower for word in ("sql", "database", "postgres", "mysql", "sqlite", "relational", "document database", "graph database")):
        blocks = [
            PlanBlock(ref="database_overview", kind="rich_text", title="Choosing the right database", body="PostgreSQL is the safest general-purpose default; choose a specialist when deployment shape or workload clearly demands it.", variant="plain"),
            PlanBlock(ref="database_options", kind="comparison", title="Options by workload", variant="sketch", items=[
                BlockItem(label="General purpose", title="PostgreSQL", body="Transactions, joins, extensions, and mature operations."),
                BlockItem(label="Embedded", title="SQLite", body="A complete database in one portable file."),
                BlockItem(label="Web workloads", title="MySQL", body="Straightforward operations and broad hosting support."),
                BlockItem(label="Analytics", title="DuckDB", body="Fast local analysis over files and columnar data."),
            ]),
            PlanBlock(ref="database_rule", kind="callout", title="Default deliberately", body="Start with PostgreSQL unless a concrete constraint points elsewhere.", variant="accent"),
        ]
        summary = f"A practical database decision guide prompted by: {query}"
    elif any(word in lower for word in ("physics", "relativity", "speed of light", "gravity", "quantum", "time slows")):
        blocks = [
            PlanBlock(ref="physics_idea", kind="hero", title=_title_from_query(query), body="A visual explanation grounded in the physical intuition first, then the governing relationship.", variant="plain"),
            PlanBlock(ref="physics_visual", kind="diagram", title="What changes between observers", variant="sketch", items=[
                BlockItem(title="Observer", body="Measures events with a clock and ruler."),
                BlockItem(title="Relative motion", body="Changes how space and time divide the interval."),
                BlockItem(title="Invariant", body="The speed of light stays the same."),
                BlockItem(title="Consequence", body="Elapsed time differs between paths."),
            ]),
            PlanBlock(ref="physics_detail", kind="rich_text", title="The useful intuition", body="The model will connect the diagram to the precise explanation.", variant="quiet"),
        ]
        summary = f"A visual physics explanation prompted by: {query}"
    elif any(word in lower for word in ("trip", "travel", "itinerary", "days in", "visit")):
        blocks = [
            PlanBlock(ref="travel_overview", kind="hero", title=title, body="A paced route with enough structure to book confidently and enough slack to enjoy the trip.", variant="plain"),
            PlanBlock(ref="travel_route", kind="timeline", title="A relaxed route", variant="sketch", items=[
                BlockItem(title="Arrival", body="Settle in and keep the first day light."),
                BlockItem(title="First base", body="Explore deeply instead of changing hotels daily."),
                BlockItem(title="Second base", body="Use a simple transfer and one flexible day."),
                BlockItem(title="Departure", body="Finish near the airport with breathing room."),
            ]),
            PlanBlock(ref="travel_note", kind="callout", title="Protect the pace", body="Leave roughly one day in four lightly planned.", variant="accent"),
        ]
        summary = f"A practical itinerary prompted by: {query}"
    elif any(word in lower for word in ("how", "process", "steps", "workflow", "build", "implement")):
        blocks = [
            PlanBlock(ref="process_overview", kind="rich_text", title=_title_from_query(query), body=f"A direct explanation of {query}", variant="plain"),
            PlanBlock(ref="process_steps", kind="process", title="How it works", variant="sketch", items=[
                BlockItem(title="Start", body="Establish the inputs and constraints."),
                BlockItem(title="Transform", body="Apply the central mechanism."),
                BlockItem(title="Validate", body="Check the result against the goal."),
                BlockItem(title="Iterate", body="Refine using what the check revealed."),
            ]),
            PlanBlock(ref="process_note", kind="callout", title="The key tradeoff", body="Prefer the simplest version that preserves the important behavior.", variant="quiet"),
        ]
        summary = f"A visual process explanation prompted by: {query}"
    else:
        blocks = [
            PlanBlock(ref="answer", kind="hero", title=_title_from_query(query), body=f"A focused visual answer to: {query}", variant="plain"),
            PlanBlock(ref="explanation", kind="rich_text", title="The core idea", body="The answer starts with the essential idea, then adds the detail needed to use it.", variant="plain"),
            PlanBlock(ref="takeaways", kind="list", title="What to remember", variant="sketch", items=[
                BlockItem(title="Core principle"), BlockItem(title="Important tradeoff"), BlockItem(title="Practical next step"),
            ]),
        ]
        summary = f"A visual explanation prompted by: {query}"

    return CanvasPlan(
        mode=mode,
        target_artifact_id=target.id if target else None,
        insert_after_block_id=anchor.id if anchor else None,
        title=title,
        summary=summary,
        layout="editorial",
        blocks=blocks[:4],
    )
