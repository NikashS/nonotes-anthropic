from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class Base(DeclarativeBase):
    pass


class Canvas(Base):
    __tablename__ = "canvases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="My knowledge space")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    canvas_id: Mapped[str] = mapped_column(ForeignKey("canvases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="composition")
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ArtifactRevision(Base):
    __tablename__ = "artifact_revisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SceneElement(Base):
    __tablename__ = "scene_elements"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    shape: Mapped[str | None] = mapped_column(String(30), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    style: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("scene_elements.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("scene_elements.id"))
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    style: Mapped[dict] = mapped_column(JSON, default=dict)


class Relationship(Base):
    __tablename__ = "relationships"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    target_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    predicate: Mapped[str] = mapped_column(String(80), default="related_to")
    origin: Mapped[str] = mapped_column(String(30), default="ai")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)


class InteractionRun(Base):
    __tablename__ = "interaction_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    canvas_id: Mapped[str] = mapped_column(ForeignKey("canvases.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    behavior: Mapped[str | None] = mapped_column(String(30), nullable=True)
    focused_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


default_database_url = "sqlite:////tmp/nonotes.db" if os.getenv("VERCEL") else "sqlite:///./nonotes.db"
database_url = os.getenv("DATABASE_URL", default_database_url)
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def init_database() -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if session.get(Canvas, "main"):
            return
        canvas = Canvas(id="main", name="My knowledge space")
        artifact = Artifact(
            id="artifact_no_notes",
            canvas_id="main",
            title="The No Notes idea",
            summary="A spatial AI workspace that retrieves durable artifacts instead of asking users to find old chats.",
        )
        elements = [
            SceneElement(id="element_vision", artifact_id=artifact.id, kind="text", content="# No Notes\nAsk for what you remember. The system finds the right work and continues it **in place**.", x=20, y=20, width=480, height=150, style={}),
            SceneElement(id="element_artifacts", artifact_id=artifact.id, kind="shape", shape="rectangle", content="### Durable artifacts\nDocuments, decisions, entities, and visualizations—not chat transcripts.", x=20, y=245, width=280, height=150, style={}),
            SceneElement(id="element_retrieve", artifact_id=artifact.id, kind="shape", shape="rectangle", content="### Retrieve context\nSelect the smallest useful set of related artifacts.", x=400, y=245, width=280, height=150, style={}),
            SceneElement(id="element_continue", artifact_id=artifact.id, kind="shape", shape="ellipse", content="### Continue the work\nModify, extend, or navigate.", x=780, y=235, width=270, height=170, style={}),
            SceneElement(id="element_principle", artifact_id=artifact.id, kind="text", content="The canvas is persistent. A follow-up should build on the focused output unless the intent is genuinely separate.", x=400, y=475, width=430, height=110, style={}),
        ]
        connectors = [
            Connector(id="connector_1", artifact_id=artifact.id, source_id="element_artifacts", target_id="element_retrieve", label="becomes searchable", style={}),
            Connector(id="connector_2", artifact_id=artifact.id, source_id="element_retrieve", target_id="element_continue", label="restores context", style={}),
        ]
        session.add_all([canvas, artifact, *elements, *connectors])
        session.commit()
        write_revision(session, artifact.id, None)
        session.commit()


def serialize_element(element: SceneElement) -> dict:
    return {
        "id": element.id,
        "artifact_id": element.artifact_id,
        "kind": element.kind,
        "shape": element.shape,
        "content": element.content,
        "x": element.x,
        "y": element.y,
        "width": element.width,
        "height": element.height,
        "style": element.style or {},
        "revision": element.revision,
    }


def serialize_connector(connector: Connector) -> dict:
    return {
        "id": connector.id,
        "artifact_id": connector.artifact_id,
        "source_id": connector.source_id,
        "target_id": connector.target_id,
        "label": connector.label,
        "style": connector.style or {},
    }


def serialize_artifact(artifact: Artifact) -> dict:
    return {
        "id": artifact.id,
        "title": artifact.title,
        "summary": artifact.summary,
        "kind": artifact.kind,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
    }


def canvas_snapshot(session: Session, canvas_id: str = "main") -> dict:
    canvas = session.get(Canvas, canvas_id)
    if not canvas:
        canvas = Canvas(id=canvas_id, name="My knowledge space")
        session.add(canvas)
        session.commit()
    artifacts = list(session.scalars(select(Artifact).where(Artifact.canvas_id == canvas_id)))
    artifact_ids = [artifact.id for artifact in artifacts]
    elements = list(session.scalars(select(SceneElement).where(SceneElement.artifact_id.in_(artifact_ids)))) if artifact_ids else []
    connectors = list(session.scalars(select(Connector).where(Connector.artifact_id.in_(artifact_ids)))) if artifact_ids else []
    return {
        "id": canvas.id,
        "name": canvas.name,
        "artifacts": [serialize_artifact(item) for item in artifacts],
        "elements": [serialize_element(item) for item in elements],
        "connectors": [serialize_connector(item) for item in connectors],
    }


def write_revision(session: Session, artifact_id: str, run_id: str | None) -> None:
    elements = list(session.scalars(select(SceneElement).where(SceneElement.artifact_id == artifact_id)))
    connectors = list(session.scalars(select(Connector).where(Connector.artifact_id == artifact_id)))
    latest = session.scalars(
        select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact_id).order_by(ArtifactRevision.number.desc())
    ).first()
    session.add(ArtifactRevision(
        id=new_id("revision"),
        artifact_id=artifact_id,
        run_id=run_id,
        number=(latest.number + 1) if latest else 1,
        snapshot={
            "elements": [serialize_element(item) for item in elements],
            "connectors": [serialize_connector(item) for item in connectors],
        },
    ))


def retrieve_artifacts(session: Session, canvas_id: str, query: str, focused_artifact_id: str | None, limit: int = 5) -> list[Artifact]:
    artifacts = list(session.scalars(select(Artifact).where(Artifact.canvas_id == canvas_id)))
    terms = {word.strip(".,?!:;()[]{}\"").lower() for word in query.split() if len(word) > 2}

    def score(artifact: Artifact) -> float:
        haystack = f"{artifact.title} {artifact.summary}".lower()
        lexical = sum(1.0 for term in terms if term in haystack)
        focus = 8.0 if artifact.id == focused_artifact_id else 0.0
        return lexical + focus

    return sorted(artifacts, key=score, reverse=True)[:limit]


init_database()
