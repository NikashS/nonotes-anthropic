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
    selected_element_ids: list[str] = Field(default_factory=list)
    recent_focus_history: list[str] = Field(default_factory=list)


class InteractionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    context: InteractionContext = Field(default_factory=InteractionContext)


class PositionUpdate(BaseModel):
    x: float
    y: float


class PlanElement(BaseModel):
    ref: str = Field(description="A short unique reference used by connectors")
    kind: Literal["text", "shape"]
    shape: Literal["rectangle", "ellipse", "pill"] | None = None
    content: str
    direction: Literal["right", "below", "left", "above", "center"] = "right"
    relative_to: str | None = Field(default=None, description="A new element ref or existing element ID")
    width: int = Field(default=300, ge=140, le=680)
    height: int = Field(default=150, ge=70, le=480)


class PlanUpdate(BaseModel):
    element_id: str
    content: str


class PlanConnection(BaseModel):
    source_ref: str
    target_ref: str
    label: str | None = None


class CanvasPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["modify", "extend", "navigate", "new"]
    title: str
    summary: str
    target_artifact_id: str | None = None
    updates: list[PlanUpdate] = Field(default_factory=list)
    elements: list[PlanElement] = Field(default_factory=list)
    connections: list[PlanConnection] = Field(default_factory=list)

