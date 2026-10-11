"""FastAPI entry point for the SortWise AI backend."""

from uuid import uuid4

from fastapi import FastAPI, File, Form, UploadFile

from schemas import AnalysisResponse

app = FastAPI(
    title="SortWise AI API",
    description="Image upload API for the SortWise waste-sorting assistant.",
    version="0.2.0",
)


@app.get("/", tags=["health"])
def read_root() -> dict[str, str]:
    """Return a welcome response and API documentation location."""
    return {"message": "SortWise AI API is running", "docs": "/docs"}


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Provide a simple health check for local development and deployment."""
    return {"status": "ok"}


@app.post(
    "/api/v1/analyses",
    status_code=200,
    response_model=AnalysisResponse,
    tags=["analyses"],
    summary="Receive an image for waste analysis",
    response_description="Completed analysis response",
)
async def receive_analysis(
    image: UploadFile = File(description="Image file uploaded by the frontend"),
    description: str | None = Form(
        default=None,
        description="Optional context about the item, such as whether it contained food",
    ),
) -> AnalysisResponse:
    """Receive an image and return a placeholder result until AI is connected.

    The frontend should validate formats and sizes before upload. This endpoint
    closes and discards the upload without saving or analyzing it.
    """
    request_id = str(uuid4())
    # Demo fallback only: no model is called, so never infer a category from
    # the uploaded image. Replace this result with validated model output when
    # vision integration is implemented.
    response = {
        "request_id": request_id,
        "status": "completed",
        "result": {
            "item_name": "Unidentified item",
            "category": "unknown",
            "material": "unknown",
            "confidence": 0.0,
            "evidence": "Image analysis is not configured; the uploaded image has not been classified.",
            "disposal_guidance": "Check your local waste authority's guidance before disposing of this item.",
            "preparation_steps": [],
            "warnings": [
                "This is placeholder data, not an AI-generated result.",
                "Local disposal rules vary.",
            ],
        },
    }
    await image.close()
    return AnalysisResponse(**response)
