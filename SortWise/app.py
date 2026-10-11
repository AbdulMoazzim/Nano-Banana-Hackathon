import logging
import os
from uuid import uuid4
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

try:
    # pyrefly: ignore [missing-import]
    import spaces

    @spaces.GPU
    def _init_gpu():
        """Satisfy ZeroGPU startup check."""
        return True
except ImportError:
    pass

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
allowed_origins = [frontend_origin] if frontend_origin else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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

import io
import asyncio
import gradio as gr
from fastapi.openapi.docs import get_swagger_ui_html

# 1. Interactive Testing Function directly on the Gradio page
def test_classifier(image, description=""):
    if image is None:
        return {"error": "Please upload an image to test"}
    
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    image_bytes = buf.getvalue()
    
    try:
        identification = asyncio.run(analyze_image(image_bytes, description))
    except Exception as e:
        return {"error": str(e)}
        
    disposal = decision_for(identification["category"])
    return {
        "item_name": identification["item_name"],
        "category": disposal["category"],
        "material": identification["material"],
        "confidence": identification["confidence"],
        "evidence": identification["evidence"],
        "disposal_guidance": disposal["disposal_guidance"],
        "preparation_steps": disposal["preparation_steps"],
        "warnings": disposal["warnings"],
    }

# 2. Gradio Web Interface
with gr.Blocks(title="SortWise AI API") as demo:
    gr.Markdown("# 🚀 SortWise AI Backend & Trash-Net Engine")
    gr.Markdown(
        "Upload an image below to test the AI classification and disposal guidance live. "
        "API docs available at [`/docs`](/docs)."
    )
    
    with gr.Row():
        with gr.Column():
            img_input = gr.Image(type="pil", label="Upload Waste Image")
            desc_input = gr.Textbox(label="Optional Description", placeholder="e.g. empty plastic soda bottle")
            submit_btn = gr.Button("Analyze Waste", variant="primary")
        with gr.Column():
            json_output = gr.JSON(label="Analysis Result")
            
    submit_btn.click(fn=test_classifier, inputs=[img_input, desc_input], outputs=json_output)

# 3. Attach FastAPI API endpoints (/api/v1/analyses, /health)
demo.app.include_router(app.router)

# 4. Explicitly attach Swagger UI to /docs and /openapi.json
@demo.app.get("/docs", include_in_schema=False)
async def swagger_docs():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="SortWise API - Swagger Docs")

@demo.app.get("/openapi.json", include_in_schema=False)
async def openapi_schema():
    return app.openapi()

if __name__ == "__main__":
    demo.launch()
else:
    demo.launch()




