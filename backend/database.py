from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from dataclasses import dataclass
import re

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool

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


class ArtifactRegion(Base):
    __tablename__ = "artifact_regions"
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    width: Mapped[float] = mapped_column(Float, default=960)
    height: Mapped[float] = mapped_column(Float, default=680)
    layout: Mapped[str] = mapped_column(String(40), default="editorial")
    accent: Mapped[str] = mapped_column(String(40), default="moss")


class ArtifactBlock(Base):
    __tablename__ = "artifact_blocks"
    __table_args__ = (Index("ix_artifact_blocks_artifact_order", "artifact_id", "order"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    kind: Mapped[str] = mapped_column(String(40))
    variant: Mapped[str] = mapped_column(String(40), default="plain")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    html: Mapped[str] = mapped_column(Text, default="")
    order: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class ArtifactRevision(Base):
    __tablename__ = "artifact_revisions"
    __table_args__ = (Index("ix_artifact_revisions_artifact_number", "artifact_id", "number"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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

if database_url.startswith("sqlite"):
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"check_same_thread": False})
else:
    # Vercel instances are transient. Let Supavisor own connection pooling and
    # disable prepared statements, which transaction-pooling mode cannot retain.
    connect_args = {"prepare_threshold": None} if ":6543/" in database_url else {}
    engine = create_engine(database_url, pool_pre_ping=True, poolclass=NullPool, connect_args=connect_args)


def serialize_region(region: ArtifactRegion) -> dict:
    return {
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
        "layout": region.layout,
        "accent": region.accent,
    }


def serialize_artifact(artifact: Artifact, region: ArtifactRegion | None = None) -> dict:
    result = {
        "id": artifact.id,
        "title": artifact.title,
        "summary": artifact.summary,
        "kind": artifact.kind,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
    }
    if region:
        result.update(serialize_region(region))
    return result


def serialize_block(block: ArtifactBlock) -> dict:
    return {
        "id": block.id,
        "artifact_id": block.artifact_id,
        "kind": block.kind,
        "variant": block.variant,
        "content": block.content or {},
        "html": block.html,
        "order": block.order,
        "revision": block.revision,
    }


def canvas_snapshot(session: Session, canvas_id: str = "main") -> dict:
    canvas = session.get(Canvas, canvas_id)
    if not canvas:
        canvas = Canvas(id=canvas_id, name="My knowledge space")
        session.add(canvas)
        session.commit()
    artifacts = list(session.scalars(select(Artifact).where(Artifact.canvas_id == canvas_id)))
    artifact_ids = [artifact.id for artifact in artifacts]
    regions = list(session.scalars(select(ArtifactRegion).where(ArtifactRegion.artifact_id.in_(artifact_ids)))) if artifact_ids else []
    region_map = {region.artifact_id: region for region in regions}
    blocks = list(session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id.in_(artifact_ids)).order_by(ArtifactBlock.order))) if artifact_ids else []
    return {
        "id": canvas.id,
        "name": canvas.name,
        "artifacts": [serialize_artifact(item, region_map.get(item.id)) for item in artifacts],
        "blocks": [serialize_block(item) for item in blocks],
    }


def write_revision(session: Session, artifact_id: str, run_id: str | None) -> None:
    blocks = list(session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact_id).order_by(ArtifactBlock.order)))
    region = session.get(ArtifactRegion, artifact_id)
    latest = session.scalars(select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact_id).order_by(ArtifactRevision.number.desc())).first()
    session.add(ArtifactRevision(
        id=new_id("revision"),
        artifact_id=artifact_id,
        run_id=run_id,
        number=(latest.number + 1) if latest else 1,
        snapshot={"region": serialize_region(region) if region else None, "blocks": [serialize_block(item) for item in blocks]},
    ))


@dataclass
class RetrievedArtifact:
    artifact: Artifact
    semantic_score: float = 0
    lexical_score: float = 0
    focus_score: float = 0
    score: float = 0


_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "build", "can", "could", "for", "from",
    "have", "how", "into", "more", "that", "the", "their", "tell", "this", "what", "when", "where",
    "which", "with", "would", "you", "your",
}


def _terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2 and word not in _STOP_WORDS}


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def retrieve_artifacts(
    session: Session,
    canvas_id: str,
    query: str,
    focused_artifact_id: str | None,
    embedding: list[float] | None = None,
    limit: int = 6,
) -> list[RetrievedArtifact]:
    artifacts = list(session.scalars(select(Artifact).where(Artifact.canvas_id == canvas_id)))
    semantic_scores: dict[str, float] = {}
    if embedding and session.bind and session.bind.dialect.name == "postgresql":
        rows = session.execute(text("""
            select artifact_id, semantic_score
            from public.match_artifacts(cast(:embedding as extensions.vector), :canvas_id, :match_count)
        """), {
            "embedding": _vector_literal(embedding),
            "canvas_id": canvas_id,
            "match_count": max(limit * 2, 8),
        })
        semantic_scores = {row.artifact_id: max(0.0, float(row.semantic_score)) for row in rows}

    query_terms = _terms(query)
    candidates: list[RetrievedArtifact] = []
    for artifact in artifacts:
        artifact_terms = _terms(f"{artifact.title} {artifact.summary}")
        overlap = len(query_terms & artifact_terms)
        lexical = overlap / max(1, len(query_terms | artifact_terms))
        semantic = semantic_scores.get(artifact.id, 0.0)
        focus = 0.07 if artifact.id == focused_artifact_id and artifact.kind != "welcome" else 0.0
        # Semantics dominate; lexical overlap and focus break close calls.
        score = semantic * 0.82 + lexical * 0.13 + focus
        if artifact.kind == "welcome":
            score = -1
        candidates.append(RetrievedArtifact(artifact, semantic, lexical, focus, score))
    return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]


def artifact_embedding_text(session: Session, artifact: Artifact) -> str:
    blocks = list(session.scalars(
        select(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id).order_by(ArtifactBlock.order)
    ))
    parts = [artifact.title, artifact.summary]
    for block in blocks:
        content = block.content or {}
        parts.extend([str(content.get("title", "")), str(content.get("body", ""))])
        for item in content.get("items", []):
            if isinstance(item, dict):
                parts.extend([str(item.get("title", "")), str(item.get("body", ""))])
    return "\n".join(part for part in parts if part).strip()[:16_000]


def store_artifact_embedding(session: Session, artifact_id: str, source_text: str, embedding: list[float]) -> None:
    if not session.bind or session.bind.dialect.name != "postgresql":
        return
    session.execute(text("""
        update artifacts
        set embedding = cast(:embedding as extensions.vector),
            embedding_text = :source_text,
            embedding_updated_at = now()
        where id = :artifact_id
    """), {
        "embedding": _vector_literal(embedding),
        "source_text": source_text,
        "artifact_id": artifact_id,
    })


def init_database() -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        canvas = session.get(Canvas, "main")
        if not canvas:
            canvas = Canvas(id="main", name="My knowledge space")
            session.add(canvas)
        artifact = session.get(Artifact, "artifact_no_notes")
        if not artifact:
            artifact = Artifact(
                id="artifact_no_notes",
                canvas_id="main",
                kind="welcome",
                title="No Notes",
                summary="A spatial AI workspace that retrieves durable artifacts instead of asking users to find old chats.",
            )
            session.add(artifact)
        elif artifact.kind != "welcome":
            artifact.kind = "welcome"
        if artifact.title == "The No Notes idea":
            artifact.title = "No Notes"
        region = session.get(ArtifactRegion, artifact.id)
        if not region:
            session.add(ArtifactRegion(artifact_id=artifact.id, x=40, y=20, width=1040, height=900, layout="editorial", accent="moss"))
        else:
            region.height = max(region.height, 900)
        has_blocks = session.scalars(select(ArtifactBlock).where(ArtifactBlock.artifact_id == artifact.id)).first()
        if not has_blocks:
            seed_blocks = [
                ArtifactBlock(id="block_vision", artifact_id=artifact.id, kind="hero", variant="plain", order=0, content={"eyebrow": "A spatial AI workspace", "title": "No Notes", "body": "Ask for what you remember. The system finds the right work and continues it in place."}, html="<p class=\"eyebrow\">A spatial AI workspace</p><h1>No Notes</h1><p class=\"lede\">Ask for what you remember. The system finds the right work and continues it <strong>in place</strong>.</p>"),
                ArtifactBlock(id="block_flow", artifact_id=artifact.id, kind="process", variant="sketch", order=1, content={"title": "From memory to momentum", "items": [{"title": "Ask naturally", "body": ""}, {"title": "Retrieve durable artifacts", "body": ""}, {"title": "Continue the work", "body": ""}]}, html="<h2>From memory to momentum</h2><div class=\"process-line\" data-count=\"3\"><div><strong>Ask naturally</strong></div><div><strong>Retrieve durable artifacts</strong></div><div><strong>Continue the work</strong></div></div>"),
                ArtifactBlock(id="block_principles", artifact_id=artifact.id, kind="comparison", variant="paper", order=2, content={"title": "The interaction model", "items": [{"label": "Instead of", "title": "No chats to find", "body": "Intent is the navigation."}, {"label": "Continuity", "title": "No blank canvas on follow-up", "body": "Focused work changes in place."}, {"label": "Expression", "title": "No diagram-only answers", "body": "Text, visuals, tables, and documents coexist."}]}, html="<h2>The interaction model</h2><div class=\"comparison-grid\"><article><small>Instead of</small><strong>No chats to find</strong><p>Intent is the navigation.</p></article><article><small>Continuity</small><strong>No blank canvas on follow-up</strong><p>Focused work changes in place.</p></article><article><small>Expression</small><strong>No diagram-only answers</strong><p>Text, visuals, tables, and documents coexist.</p></article></div>"),
                ArtifactBlock(id="block_note", artifact_id=artifact.id, kind="callout", variant="ink", order=3, content={"title": "The invariant", "body": "A follow-up modifies or extends the focused artifact. Only genuinely separate intent creates a new spatial region."}, html="<span class=\"scribble\">The invariant</span><p>A follow-up modifies or extends the focused artifact. Only genuinely separate intent creates a new spatial region.</p>"),
            ]
            session.add_all(seed_blocks)
        else:
            principles = session.get(ArtifactBlock, "block_principles")
            if principles and any(isinstance(item, str) for item in (principles.content or {}).get("items", [])):
                principles.content = {
                    "title": "The interaction model",
                    "items": [
                        {"label": "Instead of", "title": "No chats to find", "body": "Intent is the navigation."},
                        {"label": "Continuity", "title": "No blank canvas on follow-up", "body": "Focused work changes in place."},
                        {"label": "Expression", "title": "No diagram-only answers", "body": "Text, visuals, tables, and documents coexist."},
                    ],
                }
        session.commit()
        if not session.scalars(select(ArtifactRevision).where(ArtifactRevision.artifact_id == artifact.id)).first():
            write_revision(session, artifact.id, None)
            session.commit()


# Local SQLite needs convenient bootstrapping. Production Postgres is managed
# by migrations; running DDL and seed reconciliation in every new Vercel
# function instance adds avoidable cold-start work before the first request.
if not os.getenv("VERCEL"):
    init_database()
