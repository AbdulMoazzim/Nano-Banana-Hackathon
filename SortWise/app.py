import logging
import os
from uuid import uuid4
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from decision_engine import decision_for
from schemas import AnalysisResponse, WasteCondition, WasteResult
from vision import (
    ImageValidationError,
    MAX_IMAGE_BYTES,
    VisionError,
    analyze_image,
    assess_condition,
)

logger = logging.getLogger(__name__)
app = FastAPI(
    title="SortWise AI API",
    description="Image upload API for the SortWise waste-sorting assistant.",
    version="0.3.0",
)

frontend_origin = os.environ.get("FRONTEND_ORIGIN", "").strip().rstrip("/")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin] if frontend_origin else [],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def read_root():
    return {"message": "SortWise AI API is running", "docs": "/docs"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/v1/analyses", status_code=200, response_model=AnalysisResponse)
async def receive_analysis(
    image: UploadFile = File(description="Image file uploaded by the frontend"),
    description: str | None = Form(
        default=None, description="Optional context about the item"
    ),
):
    try:
        image_bytes = await image.read(MAX_IMAGE_BYTES + 1)

        # --- classification (existing path) ---
        try:
            identification = await analyze_image(image_bytes, description)
        except ImageValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except VisionError as exc:
            logger.warning(
                "Vision analysis failed (%s): %s", type(exc).__name__, str(exc)
            )
            identification = {
                "item_name": "Unidentified item",
                "category": "unknown",
                "material": "unknown",
                "confidence": 0.0,
                "evidence": (
                    "Image analysis was unavailable; the item was not classified reliably."
                ),
            }

        # --- condition assessment (optional; never fails the request) ---
        condition_dict = await assess_condition(image_bytes, description)
        try:
            condition = WasteCondition(**condition_dict)
        except Exception as exc:
            logger.warning(
                "WasteCondition construction failed (%s): %s",
                type(exc).__name__,
                str(exc),
            )
            condition = None

        disposal = decision_for(identification["category"])
        return AnalysisResponse(
            request_id=str(uuid4()),
            status="completed",
            result=WasteResult(
                item_name=str(identification["item_name"]),
                category=disposal["category"],  # type: ignore[arg-type]
                material=str(identification["material"]),
                confidence=float(identification["confidence"]),  # type: ignore[arg-type]
                evidence=str(identification["evidence"]),
                disposal_guidance=str(disposal["disposal_guidance"]),
                preparation_steps=list(disposal["preparation_steps"]),  # type: ignore[arg-type]
                warnings=list(disposal["warnings"]),  # type: ignore[arg-type]
                condition=condition,
            ),
        )
    finally:
        await image.close()
