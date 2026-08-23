from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from html import escape

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

try:
    from .database import (
        Artifact, ArtifactBlock, ArtifactRegion, InteractionRun, canvas_snapshot,
        engine, new_id, serialize_artifact, serialize_block, utcnow, write_revision,
    )
    from .planner import make_plan
    from .schemas import BlockItem, InteractionRequest, PlanBlock
except ImportError:
    from database import (
        Artifact, ArtifactBlock, ArtifactRegion, InteractionRun, canvas_snapshot,
        engine, new_id, serialize_artifact, serialize_block, utcnow, write_revision,
    )
    from planner import make_plan
    from schemas import BlockItem, InteractionRequest, PlanBlock

app = FastAPI(title="No Notes API", version="0.2.0")
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
        steps = '<div class="process-line">' + '<i></i>'.join(_item_html(item, "div") for item in items) + "</div>"
        return [f"<h2>{safe_title}</h2>" if title else "", steps]
    if kind == "comparison":
        return [f"<h2>{safe_title}</h2>" if title else "", '<div class="comparison-grid">' + "".join(_item_html(item) for item in items) + "</div>"]
    if kind == "timeline":
        return [f"<h2>{safe_title}</h2>" if title else "", '<ol class="timeline">' + "".join(_item_html(item, "li") for item in items) + "</ol>"]
    if kind == "diagram":
        nodes = "".join(f'<article><b>{index + 1}</b><strong>{escape(item.title)}</strong><p>{escape(item.body)}</p></article>' for index, item in enumerate(items))
        return [f"<h2>{safe_title}</h2>" if title else "", f'<p class="diagram-intro">{safe_body}</p>' if body else "", f'<div class="diagram-flow">{nodes}</div>']
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
    return StreamingResponse(_interaction_stream(request), media_type="application/x-ndjson")


async def _interaction_stream(request: InteractionRequest) -> AsyncIterator[str]:
    run_id = new_id("run")
    seq = 0

    def event(name: str, payload: dict) -> str:
        nonlocal seq
        seq += 1
        return json.dumps({"event": name, "seq": seq, "run_id": run_id, "payload": payload}, default=str) + "\n"

    with Session(engine) as session:
        session.add(InteractionRun(id=run_id, canvas_id=request.context.canvas_id, message=request.message, focused_artifact_id=request.context.focused_artifact_id, context=request.context.model_dump()))
        session.commit()

    yield event("run.started", {"message": request.message})
    yield event("context.selected", {"label": "Finding the right place for this"})

    try:
        with Session(engine) as session:
            plan, planner = await make_plan(session, request)
            run = session.get(InteractionRun, run_id)
            assert run
            run.behavior = plan.mode

            artifact = session.get(Artifact, plan.target_artifact_id) if plan.target_artifact_id else None
            is_new = plan.mode == "new" or not artifact
            if is_new:
                artifact = Artifact(id=new_id("artifact"), canvas_id=request.context.canvas_id, title=plan.title, summary=plan.summary)
                session.add(artifact)
                session.flush()
                region = _new_region(session, artifact.id, plan.layout)
                session.add(region)
            else:
                region = session.get(ArtifactRegion, artifact.id)
                if not region:
                    region = ArtifactRegion(artifact_id=artifact.id)
                    session.add(region)
                if plan.mode == "modify" and plan.title:
                    artifact.title = plan.title
                artifact.summary = plan.summary or artifact.summary
                artifact.updated_at = utcnow()
            session.flush()

            transition = "topic-shift" if is_new else "continuation"
            yield event("artifact.started", {"artifact": serialize_artifact(artifact, region), "mode": "new" if is_new else plan.mode, "transition": transition})

            focus_ids: list[str] = []
            for update in plan.updates:
                block = session.get(ArtifactBlock, update.block_id)
                if not block or block.artifact_id != artifact.id:
                    continue
                current = block.content or {}
                items = update.items or [BlockItem.model_validate(item) for item in current.get("items", [])]
                title = update.title or current.get("title", "")
                eyebrow = update.eyebrow or current.get("eyebrow", "")
                body = update.body or current.get("body", "")
                block.content = {"title": title, "eyebrow": eyebrow, "body": body, "items": [item.model_dump() for item in items]}
                block.variant = update.variant or block.variant
                block.html = ""
                block.revision += 1
                focus_ids.append(block.id)
                session.flush()
                yield event("block.started", {"block": serialize_block(block), "replacing": True})
                for fragment in _compile_fragments(block.kind, title, eyebrow, body, items):
                    if not fragment:
                        continue
                    block.html += fragment
                    yield event("block.html_delta", {"block_id": block.id, "html": fragment})
                    await asyncio.sleep(0.045)
                yield event("block.committed", {"block_id": block.id})

            next_order = session.scalar(select(func.max(ArtifactBlock.order)).where(ArtifactBlock.artifact_id == artifact.id))
            next_order = (next_order + 1) if next_order is not None else 0
            for index, addition in enumerate(plan.blocks):
                block = ArtifactBlock(
                    id=new_id("block"), artifact_id=artifact.id, kind=addition.kind,
                    variant=addition.variant, content=_content(addition), html="", order=next_order + index,
                )
                session.add(block)
                session.flush()
                focus_ids.append(block.id)
                yield event("block.started", {"block": serialize_block(block), "replacing": False})
                for fragment in _compile_fragments(addition.kind, addition.title, addition.eyebrow, addition.body, addition.items):
                    if not fragment:
                        continue
                    block.html += fragment
                    yield event("block.html_delta", {"block_id": block.id, "html": fragment})
                    await asyncio.sleep(0.055)
                yield event("block.committed", {"block_id": block.id})

            total_blocks = session.scalar(select(func.count()).select_from(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id)) or 1
            region.height = max(region.height, 380 + total_blocks * 190)
            if not focus_ids:
                focus_ids = [block.id for block in session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id))]
            write_revision(session, artifact.id, run_id)
            run.status = "completed"
            run.completed_at = utcnow()
            session.commit()

            yield event("artifact.committed", {"artifact": serialize_artifact(artifact, region)})
            yield event("viewport.focus_requested", {"artifact_id": artifact.id, "block_ids": focus_ids, "transition": transition})
            yield event("run.completed", {"label": "Ready", "mode": "new" if is_new else plan.mode, "planner": planner})
    except Exception as exc:
        with Session(engine) as session:
            run = session.get(InteractionRun, run_id)
            if run:
                run.status = "failed"
                run.completed_at = utcnow()
                session.commit()
        yield event("run.failed", {"message": "The response could not be completed. Please try again.", "detail": type(exc).__name__})
