from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Viewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1


class InteractionContext(BaseModel):
    canvas_id: str = "main"
    viewport: Viewport = Field(default_factory=Viewport)
    focused_artifact_id: str | None = None
    focused_block_ids: list[str] = Field(default_factory=list)
    recent_focus_history: list[str] = Field(default_factory=list)


class InteractionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    context: InteractionContext = Field(default_factory=InteractionContext)


class BlockItem(BaseModel):
    title: str
    body: str = ""
    label: str = ""


class PlanBlock(BaseModel):
    ref: str = Field(description="A short unique reference for this new block")
    kind: Literal["hero", "rich_text", "process", "comparison", "timeline", "diagram", "callout", "metrics", "list"]
    title: str = ""
    eyebrow: str = ""
    body: str = ""
    items: list[BlockItem] = Field(default_factory=list)
    variant: Literal["plain", "paper", "sketch", "ink", "accent", "quiet"] = "plain"


class PlanUpdate(BaseModel):
    block_id: str
    title: str = ""
    eyebrow: str = ""
    body: str = ""
    items: list[BlockItem] = Field(default_factory=list)
    variant: Literal["plain", "paper", "sketch", "ink", "accent", "quiet"] | None = None


class CanvasPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["modify", "extend", "navigate", "new"]
    title: str
    summary: str
    target_artifact_id: str | None = None
    layout: Literal["editorial", "board", "report"] = "editorial"
    updates: list[PlanUpdate] = Field(default_factory=list)
    blocks: list[PlanBlock] = Field(default_factory=list)
