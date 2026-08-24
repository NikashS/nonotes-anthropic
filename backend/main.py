from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from html import escape

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

try:
    from .database import (
        Artifact, ArtifactBlock, ArtifactRegion, InteractionRun, artifact_embedding_text,
        canvas_snapshot, engine, new_id, serialize_artifact, serialize_block,
        store_artifact_embedding, utcnow, write_revision,
    )
    from .embeddings import generate_embedding
    from .planner import fill_outline_blocks, make_outline
    from .schemas import BlockItem, InteractionRequest, OutlineBlock, OutlineUpdate, PlanBlock
except ImportError:
    from database import (
        Artifact, ArtifactBlock, ArtifactRegion, InteractionRun, artifact_embedding_text,
        canvas_snapshot, engine, new_id, serialize_artifact, serialize_block,
        store_artifact_embedding, utcnow, write_revision,
    )
    from embeddings import generate_embedding
    from planner import fill_outline_blocks, make_outline
    from schemas import BlockItem, InteractionRequest, OutlineBlock, OutlineUpdate, PlanBlock

app = FastAPI(title="No Notes API", version="0.2.0")
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5181", "http://127.0.0.1:5181"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "renderer": "generative-html"}


@app.get("/canvas")
def get_canvas(canvas_id: str = "main") -> dict:
    with Session(engine) as session:
        return canvas_snapshot(session, canvas_id)


def _item_html(item: BlockItem, tag: str = "article") -> str:
    label = f'<small>{escape(item.label)}</small>' if item.label else ""
    body = f'<p>{escape(item.body)}</p>' if item.body else ""
    return f'<{tag}>{label}<strong>{escape(item.title)}</strong>{body}</{tag}>'


def _compile_fragments(kind: str, title: str, eyebrow: str, body: str, items: list[BlockItem]) -> list[str]:
    safe_title, safe_eyebrow, safe_body = escape(title), escape(eyebrow), escape(body)
    if kind == "hero":
        return [
            f'<p class="eyebrow">{safe_eyebrow}</p>' if eyebrow else "",
            f"<h1>{safe_title}</h1>" if title else "",
            f'<p class="lede">{safe_body}</p>' if body else "",
        ]
    if kind == "rich_text":
        return [f"<h2>{safe_title}</h2>" if title else "", f"<p>{safe_body}</p>" if body else ""]
    if kind == "process":
        steps = f'<div class="process-line" data-count="{len(items)}">' + "".join(_item_html(item, "div") for item in items) + "</div>"
        return [f"<h2>{safe_title}</h2>" if title else "", steps]
    if kind == "comparison":
        return [f"<h2>{safe_title}</h2>" if title else "", '<div class="comparison-grid">' + "".join(_item_html(item) for item in items) + "</div>"]
    if kind == "timeline":
        return [f"<h2>{safe_title}</h2>" if title else "", '<ol class="timeline">' + "".join(_item_html(item, "li") for item in items) + "</ol>"]
    if kind == "diagram":
        nodes = "".join(f'<article><b>{index + 1}</b><strong>{escape(item.title)}</strong><p>{escape(item.body)}</p></article>' for index, item in enumerate(items))
        return [f"<h2>{safe_title}</h2>" if title else "", f'<p class="diagram-intro">{safe_body}</p>' if body else "", f'<div class="diagram-flow" data-count="{len(items)}">{nodes}</div>']
    if kind == "callout":
        return [f'<span class="scribble">{safe_title}</span>' if title else "", f"<p>{safe_body}</p>" if body else ""]
    if kind == "metrics":
        return [f"<h2>{safe_title}</h2>" if title else "", '<div class="metrics-grid">' + "".join(_item_html(item) for item in items) + "</div>"]
    return [f"<h2>{safe_title}</h2>" if title else "", f"<p>{safe_body}</p>" if body else "", "<ul>" + "".join(f"<li>{escape(item.title)}</li>" for item in items) + "</ul>" if items else ""]


def _content(block: PlanBlock) -> dict:
    return {
        "title": block.title,
        "eyebrow": block.eyebrow,
        "body": block.body,
        "items": [item.model_dump() for item in block.items],
    }


def _outline_content(slot: OutlineBlock | OutlineUpdate) -> dict:
    return {
        "title": slot.title_hint,
        "eyebrow": "",
        "body": "",
        "items": [],
        "_outline": {"item_count": slot.item_count, "size": slot.size},
    }


def _skeleton_html(slot: OutlineBlock | OutlineUpdate) -> str:
    title = f'<h2 class="outline-title">{escape(slot.title_hint)}</h2>' if slot.title_hint and slot.kind != "hero" else ""
    if slot.kind == "hero":
        return '<div class="outline-line outline-kicker"></div><div class="outline-line outline-heading"></div><div class="outline-line outline-copy"></div>'
    if slot.kind in {"process", "diagram", "comparison", "timeline", "metrics"}:
        items = "".join('<i class="outline-item"></i>' for _ in range(max(slot.item_count, 3)))
        return title + f'<div class="outline-visual" data-count="{max(slot.item_count, 3)}">{items}</div>'
    if slot.kind == "callout":
        return title + '<div class="outline-line outline-copy"></div><div class="outline-line outline-short"></div>'
    return title + '<div class="outline-line outline-copy"></div><div class="outline-line outline-copy"></div><div class="outline-line outline-short"></div>'


def _new_region(session: Session, artifact_id: str, layout: str) -> ArtifactRegion:
    farthest = session.scalar(select(func.max(ArtifactRegion.x + ArtifactRegion.width))) or 0
    count = session.scalar(select(func.count()).select_from(ArtifactRegion)) or 0
    return ArtifactRegion(
        artifact_id=artifact_id,
        x=farthest + 520,
        y=80 + (count % 2) * 180,
        width=980,
        height=760,
        layout=layout,
        accent=("rust" if count % 2 else "moss"),
    )


@app.post("/interactions")
async def interact(request: InteractionRequest) -> StreamingResponse:
    return StreamingResponse(
        _interaction_stream(request),
        media_type="application/x-ndjson",
        headers={"cache-control": "no-cache, no-transform", "x-accel-buffering": "no"},
    )


async def _interaction_stream(request: InteractionRequest) -> AsyncIterator[str]:
    run_id = new_id("run")
    seq = 0
    run_started = time.perf_counter()
    timings: dict[str, int] = {}

    def mark(stage: str, started: float) -> int:
        duration = round((time.perf_counter() - started) * 1000)
        timings[stage] = duration
        logger.info(json.dumps({"level": "info", "message": "latency.stage", "run_id": run_id, "stage": stage, "duration_ms": duration}))
        return duration

    def event(name: str, payload: dict) -> str:
        nonlocal seq
        seq += 1
        return json.dumps({"event": name, "seq": seq, "run_id": run_id, "payload": payload}, default=str) + "\n"

    yield event("run.started", {"message": request.message})

    try:
        stage_started = time.perf_counter()
        with Session(engine) as session:
            session.add(InteractionRun(id=run_id, canvas_id=request.context.canvas_id, message=request.message, focused_artifact_id=request.context.focused_artifact_id, context=request.context.model_dump()))
            session.commit()
        yield event("latency.stage", {"stage": "run.persistence", "duration_ms": mark("run.persistence", stage_started)})
        yield event("context.selected", {"label": "Sketching the shape of this"})

        with Session(engine) as session:
            stage_started = time.perf_counter()
            outline, planner, fallbacks, retrieval = await make_outline(session, request)
            yield event("latency.stage", {"stage": "outline", "duration_ms": mark("outline", stage_started)})
            stage_started = time.perf_counter()
            run = session.get(InteractionRun, run_id)
            assert run
            run.behavior = outline.mode
            run.context = {**(run.context or {}), "retrieval": retrieval}

            artifact = session.get(Artifact, outline.target_artifact_id) if outline.target_artifact_id else None
            is_new = outline.mode == "new" or not artifact
            if is_new:
                artifact = Artifact(id=new_id("artifact"), canvas_id=request.context.canvas_id, title=outline.title, summary=outline.summary)
                session.add(artifact)
                session.flush()
                region = _new_region(session, artifact.id, outline.layout)
                session.add(region)
            else:
                region = session.get(ArtifactRegion, artifact.id)
                if not region:
                    region = ArtifactRegion(artifact_id=artifact.id)
                    session.add(region)
                if outline.mode == "modify" and outline.title:
                    artifact.title = outline.title
                artifact.summary = outline.summary or artifact.summary
                artifact.updated_at = utcnow()
            session.flush()

            transition = "topic-shift" if is_new else "continuation"
            yield event("artifact.started", {"artifact": serialize_artifact(artifact, region), "mode": "new" if is_new else outline.mode, "transition": transition})

            next_order = session.scalar(select(func.max(ArtifactBlock.order)).where(ArtifactBlock.artifact_id == artifact.id))
            next_order = (next_order + 1) if next_order is not None else 0
            slots: list[tuple[OutlineBlock | OutlineUpdate, str, dict | None, bool]] = []
            focus_ids: list[str] = []

            for update in outline.updates:
                block = session.get(ArtifactBlock, update.block_id)
                if not block or block.artifact_id != artifact.id:
                    continue
                existing_content = dict(block.content or {})
                block.content = {**existing_content, "_outline": {"item_count": update.item_count, "size": update.size}}
                focus_ids.append(block.id)
                slots.append((update, block.id, existing_content, True))
                yield event("block.outlined", {"block": serialize_block(block), "replacing": True})

            for index, addition in enumerate(outline.blocks):
                block = ArtifactBlock(
                    id=new_id("block"), artifact_id=artifact.id, kind=addition.kind,
                    variant=addition.variant, content=_outline_content(addition),
                    html=_skeleton_html(addition), order=next_order + index,
                )
                session.add(block)
                session.flush()
                focus_ids.append(block.id)
                slots.append((addition, block.id, None, False))
                yield event("block.outlined", {"block": serialize_block(block), "replacing": False})

            total_blocks = session.scalar(select(func.count()).select_from(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id)) or 1
            size_adjustment = sum(100 if slot.size == "large" else -45 if slot.size == "compact" else 0 for slot, *_ in slots)
            region.height = max(region.height, 340 + total_blocks * 205 + size_adjustment)
            session.commit()
            mark("outline.persistence", stage_started)
            yield event("outline.committed", {"artifact": serialize_artifact(artifact, region), "block_ids": focus_ids})
            yield event("viewport.focus_requested", {"artifact_id": artifact.id, "block_ids": focus_ids, "transition": transition})

            embedding_task = None
            if session.bind and session.bind.dialect.name == "postgresql" and outline.mode != "navigate":
                embedding_source = f"{artifact.title}\n{artifact.summary}\n{request.message}"
                embedding_task = asyncio.create_task(generate_embedding(embedding_source))

            stage_started = time.perf_counter()
            generated = await fill_outline_blocks(
                request, artifact.title, artifact.summary,
                [(slot, existing) for slot, _, existing, _ in slots], planner, fallbacks,
            )
            yield event("latency.stage", {"stage": "content", "duration_ms": mark("content", stage_started)})

            stage_started = time.perf_counter()
            for slot, block_id, _, replacing in slots:
                content = generated[slot.ref]
                block = session.get(ArtifactBlock, block_id)
                if not block:
                    continue
                block.kind = slot.kind
                block.variant = slot.variant
                block.content = {
                    **_content(content),
                    "_outline": {"item_count": slot.item_count, "size": slot.size},
                }
                block.html = ""
                if replacing:
                    block.revision += 1
                session.flush()
                yield event("block.started", {"block": serialize_block(block), "replacing": replacing})
                for fragment in _compile_fragments(content.kind, content.title, content.eyebrow, content.body, content.items):
                    if not fragment:
                        continue
                    block.html += fragment
                    yield event("block.html_delta", {"block_id": block.id, "html": fragment})
                    await asyncio.sleep(0)
                session.commit()
                yield event("block.committed", {"block_id": block.id})
            mark("content.persistence", stage_started)

            if not focus_ids:
                focus_ids = [block.id for block in session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id))]
            write_revision(session, artifact.id, run_id)
            embedding_text = artifact_embedding_text(session, artifact)
            stage_started = time.perf_counter()
            embedding = await embedding_task if embedding_task else None
            if embedding:
                store_artifact_embedding(session, artifact.id, embedding_text, embedding)
            mark("embedding.persistence", stage_started)
            run.status = "completed"
            run.completed_at = utcnow()
            session.commit()

            yield event("artifact.committed", {"artifact": serialize_artifact(artifact, region)})
            timings["total"] = round((time.perf_counter() - run_started) * 1000)
            logger.info(json.dumps({"level": "info", "message": "latency.completed", "run_id": run_id, "timings": timings}))
            yield event("run.completed", {"mode": "new" if is_new else outline.mode, "planner": planner, "timings": timings})
    except Exception as exc:
        timings["total"] = round((time.perf_counter() - run_started) * 1000)
        logger.exception(json.dumps({
            "level": "error", "message": "latency.failed", "run_id": run_id,
            "error": type(exc).__name__, "timings": timings,
        }))
        try:
            with Session(engine) as session:
                run = session.get(InteractionRun, run_id)
                if run:
                    run.status = "failed"
                    run.completed_at = utcnow()
                    session.commit()
        except Exception:
            logger.exception(json.dumps({"level": "error", "message": "run.failure_persistence_failed", "run_id": run_id}))
        yield event("run.failed", {"message": "The response could not be completed. Please try again.", "detail": type(exc).__name__})
