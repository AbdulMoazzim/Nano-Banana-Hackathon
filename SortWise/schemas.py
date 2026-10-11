"""Pydantic schemas for SortWise API requests and responses."""

from typing import Any, Literal

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

ConditionStatus = Literal["detected", "not_detected", "unable_to_assess"]


class ConditionFinding(BaseModel):
    """Specific observation of physical wear or defect."""

    condition_type: str
    visual_evidence: str


class WasteCondition(BaseModel):
    """Physical condition of the waste item."""

    cracks_fractures: ConditionStatus = "unable_to_assess"
    holes_leaks_breakage: ConditionStatus = "unable_to_assess"
    severe_deformation: ConditionStatus = "unable_to_assess"
    image_unclear: bool = False
    findings: list[ConditionFinding | dict[str, Any]] = Field(default_factory=list)


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
    condition: WasteCondition | None = None


class AnalysisResponse(BaseModel):
    """Final response returned by POST /api/v1/analyses."""

    request_id: str
    status: Literal["completed"]
    result: WasteResult



