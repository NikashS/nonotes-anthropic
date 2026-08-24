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


class OutlineBlock(BaseModel):
    ref: str = Field(description="A short unique reference for this block")
    kind: Literal["hero", "rich_text", "process", "comparison", "timeline", "diagram", "callout", "metrics", "list"]
    title_hint: str = ""
    variant: Literal["plain", "paper", "sketch", "ink", "accent", "quiet"] = "plain"
    item_count: int = Field(default=0, ge=0, le=6)
    size: Literal["compact", "standard", "large"] = "standard"


class OutlineUpdate(OutlineBlock):
    block_id: str


class CanvasOutline(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["modify", "extend", "navigate", "new"]
    title: str
    summary: str
    target_artifact_id: str | None = None
    layout: Literal["editorial", "board", "report"] = "editorial"
    updates: list[OutlineUpdate] = Field(default_factory=list)
    blocks: list[OutlineBlock] = Field(default_factory=list)


class BlockContent(BaseModel):
    title: str = ""
    eyebrow: str = ""
    body: str = ""
    items: list[BlockItem] = Field(default_factory=list)


class CanvasPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["modify", "extend", "navigate", "new"]
    title: str
    summary: str
    target_artifact_id: str | None = None
    layout: Literal["editorial", "board", "report"] = "editorial"
    updates: list[PlanUpdate] = Field(default_factory=list)
    blocks: list[PlanBlock] = Field(default_factory=list)
