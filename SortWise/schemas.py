"""Pydantic schemas for SortWise API requests and responses."""

from typing import Literal

from pydantic import BaseModel, Field

WasteCategory = Literal[
    "plastic",
    "paper_cardboard",
    "metal",
    "glass",
    "organic",
    "general",
    "electronic",
    "unknown",
]


class WasteResult(BaseModel):
    """Classification and disposal guidance returned to the frontend."""

    item_name: str
    category: WasteCategory
    material: str
    confidence: float = Field(ge=0, le=1)
    evidence: str
    disposal_guidance: str
    preparation_steps: list[str]
    warnings: list[str]


class AnalysisResponse(BaseModel):
    """Final response returned by POST /api/v1/analyses."""

    request_id: str
    status: Literal["completed"]
    result: WasteResult


