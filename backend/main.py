from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

try:
    from .database import (
        Artifact, Connector, InteractionRun, SceneElement, canvas_snapshot, engine,
        new_id, serialize_artifact, serialize_connector, serialize_element, utcnow,
        write_revision,
    )
    from .planner import make_plan
    from .schemas import InteractionRequest, PlanElement, PositionUpdate
except ImportError:  # Vercel Services imports the entrypoint as a top-level module.
    from database import (
        Artifact, Connector, InteractionRun, SceneElement, canvas_snapshot, engine,
        new_id, serialize_artifact, serialize_connector, serialize_element, utcnow,
        write_revision,
    )
    from planner import make_plan
    from schemas import InteractionRequest, PlanElement, PositionUpdate

app = FastAPI(title="No Notes API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/canvas")
def get_canvas(canvas_id: str = "main") -> dict:
    with Session(engine) as session:
        return canvas_snapshot(session, canvas_id)


@app.patch("/elements/{element_id}/position")
def patch_element_position(element_id: str, position: PositionUpdate) -> dict:
    with Session(engine) as session:
        element = session.get(SceneElement, element_id)
        if not element:
            raise HTTPException(status_code=404, detail="Element not found")
        element.x = position.x
        element.y = position.y
        session.commit()
        return serialize_element(element)


def _words(content: str, size: int = 7) -> list[str]:
    words = content.split(" ")
    return [" ".join(words[index:index + size]) + (" " if index + size < len(words) else "") for index in range(0, len(words), size)]


def _position_for(session: Session, artifact_id: str | None, plan_element: PlanElement, refs: dict[str, str], new_index: int) -> tuple[float, float]:
    relative_id = refs.get(plan_element.relative_to or "", plan_element.relative_to)
    relative = session.get(SceneElement, relative_id) if relative_id else None
    if relative:
        gap = 100
        if plan_element.direction == "below":
            return relative.x, relative.y + relative.height + gap
        if plan_element.direction == "left":
            return relative.x - plan_element.width - gap, relative.y
        if plan_element.direction == "above":
            return relative.x, relative.y - plan_element.height - gap
        if plan_element.direction == "center":
            return relative.x, relative.y
        return relative.x + relative.width + gap, relative.y

    max_x = session.scalar(select(func.max(SceneElement.x + SceneElement.width))) or 0
    if artifact_id:
        artifact_elements = list(session.scalars(select(SceneElement).where(SceneElement.artifact_id == artifact_id)))
        if artifact_elements:
            base = artifact_elements[-1]
            return base.x + base.width + 100, base.y + (new_index % 2) * 210
    return max_x + 240, 80 + (new_index % 3) * 220


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
        run = InteractionRun(
            id=run_id,
            canvas_id=request.context.canvas_id,
            message=request.message,
            focused_artifact_id=request.context.focused_artifact_id,
            context=request.context.model_dump(),
        )
        session.add(run)
        session.commit()

    yield event("run.started", {"message": request.message})
    yield event("context.selected", {"label": "Using the focused work and related context"})

    try:
        with Session(engine) as session:
            plan, planner = await make_plan(session, request)
            run = session.get(InteractionRun, run_id)
            assert run
            run.behavior = plan.mode

            artifact = session.get(Artifact, plan.target_artifact_id) if plan.target_artifact_id else None
            if plan.mode == "new" or not artifact:
                artifact = Artifact(
                    id=new_id("artifact"),
                    canvas_id=request.context.canvas_id,
                    title=plan.title,
                    summary=plan.summary,
                )
                session.add(artifact)
            else:
                if plan.mode == "modify" and plan.title:
                    artifact.title = plan.title
                artifact.summary = plan.summary or artifact.summary
                artifact.updated_at = utcnow()
            session.flush()
            yield event("artifact.upserted", {"artifact": serialize_artifact(artifact), "mode": plan.mode})

            focus_ids: list[str] = []
            for update in plan.updates:
                element = session.get(SceneElement, update.element_id)
                if not element or element.artifact_id != artifact.id:
                    continue
                element.content = update.content
                element.revision += 1
                focus_ids.append(element.id)
                session.flush()
                yield event("element.patched", {"element": serialize_element(element)})
                yield event("element.committed", {"element_id": element.id})

            refs: dict[str, str] = {}
            for index, addition in enumerate(plan.elements):
                element_id = new_id("element")
                refs[addition.ref] = element_id
                x, y = _position_for(session, artifact.id if plan.mode != "new" else None, addition, refs, index)
                element = SceneElement(
                    id=element_id,
                    artifact_id=artifact.id,
                    kind=addition.kind,
                    shape=addition.shape if addition.kind == "shape" else None,
                    content="",
                    x=x,
                    y=y,
                    width=addition.width,
                    height=addition.height,
                    style={},
                )
                session.add(element)
                session.flush()
                focus_ids.append(element.id)
                yield event("element.created", {"element": serialize_element(element)})
                for chunk in _words(addition.content):
                    element.content += chunk
                    yield event("element.content_delta", {"element_id": element.id, "delta": chunk})
                    await asyncio.sleep(0.025)
                session.flush()
                yield event("element.committed", {"element_id": element.id})

            existing_ids = {item.id for item in session.scalars(select(SceneElement).where(SceneElement.artifact_id == artifact.id))}
            for connection in plan.connections:
                source_id = refs.get(connection.source_ref, connection.source_ref)
                target_id = refs.get(connection.target_ref, connection.target_ref)
                if source_id not in existing_ids or target_id not in existing_ids or source_id == target_id:
                    continue
                connector = Connector(
                    id=new_id("connector"),
                    artifact_id=artifact.id,
                    source_id=source_id,
                    target_id=target_id,
                    label=connection.label,
                    style={},
                )
                session.add(connector)
                session.flush()
                yield event("connector.created", {"connector": serialize_connector(connector)})

            if not focus_ids:
                focus_ids = [item.id for item in session.scalars(select(SceneElement).where(SceneElement.artifact_id == artifact.id))]
            write_revision(session, artifact.id, run_id)
            run.status = "completed"
            run.completed_at = utcnow()
            session.commit()

            yield event("canvas.focus_requested", {
                "artifact_id": artifact.id,
                "element_ids": focus_ids,
                "reason": "Continued the most relevant work" if plan.mode != "new" else "Created a separate region for new work",
            })
            yield event("run.completed", {"label": "Ready", "mode": plan.mode, "planner": planner})
    except Exception as exc:
        with Session(engine) as session:
            run = session.get(InteractionRun, run_id)
            if run:
                run.status = "failed"
                run.completed_at = utcnow()
                session.commit()
        yield event("run.failed", {"message": "The response could not be completed. Please try again.", "detail": type(exc).__name__})
