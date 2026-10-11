# SortWise AI Backend

SortWise is a waste-sorting assistant. This repository contains a FastAPI backend that accepts an image and optional description and returns the final response shape. **The current result is placeholder data; AI image analysis is not connected yet.**

## Project structure

```text
SortWise/
├── app.py              # FastAPI app, health checks, and image analysis endpoint
├── vision.py           # Reserved for future image analysis; not called by the API
├── schemas.py          # Pydantic request/response data shapes
├── decision_engine.py  # General disposal guidance; not called until analysis exists
├── requirements.txt    # Python dependencies
├── .env.example        # Future OpenRouter configuration template
├── .gitignore          # Keeps secrets and local files out of Git
└── README.md           # Setup and API contract
```

## Run locally

Use Python 3.10 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app:app --reload
```

The API runs at `http://127.0.0.1:8000`. Interactive endpoint documentation is at `http://127.0.0.1:8000/docs`; the health check is `GET /health`.

## Upload endpoint

### `POST /api/v1/analyses`

Send a `multipart/form-data` request. The image field is named `image`; `description` is optional text. The backend receives and closes the upload, but does not save, inspect, or analyze the image.

The frontend may validate supported formats and file size before sending. This endpoint currently does not apply its own format or size policy, so production deployments should add server-side limits as well.

### Browser example

```javascript
const form = new FormData();
form.append("image", selectedFile); // File from an <input type="file">
form.append("description", "Empty glass jar"); // Optional

const response = await fetch("http://127.0.0.1:8000/api/v1/analyses", {
  method: "POST",
  body: form,
});

const analysis = await response.json();
console.log(response.status); // 200
console.log(analysis.status); // "completed"
```

Do not manually set the `Content-Type` header in browser `fetch`; the browser must add the multipart boundary.

### cURL example

```bash
curl -X POST http://127.0.0.1:8000/api/v1/analyses \
  -F "image=@./sample.jpg" \
  -F "description=Empty glass jar"
```

### Successful response

HTTP status: **`200 OK`**. The endpoint currently returns a placeholder result in the final response shape:

```json
{
  "request_id": "a7e4bd5f-3ef1-4fde-bf28-03d23c55ab8e",
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
      "Local disposal rules vary."
    ]
  }
}
```

The response format is ready for a future real analysis, but the current endpoint does **not** inspect the image or use the description to generate this result. It returns the same safe fallback for every upload. There is no polling endpoint; the response is returned immediately.

## Response fields

- `request_id`: unique identifier for this request.
- `status`: currently `completed` because the placeholder response is returned synchronously.
- `result.item_name`, `category`, `material`: predicted item fields; currently safe placeholder values.
- `result.confidence`: confidence from 0 to 1; currently `0.0` because no model ran.
- `result.evidence`: explanation; currently states that the image was not classified.
- `result.disposal_guidance`: general guidance; currently directs users to local authority guidance.
- `result.preparation_steps`: steps to prepare the item, currently empty.
- `result.warnings`: caveats, including that the output is placeholder data.

## Backend modules

- **`app.py`** defines the FastAPI application, health endpoints, multipart upload route, and current fallback response.
- **`schemas.py`** defines the validated final analysis response returned to the frontend.
- **`vision.py`** is a placeholder for later image processing and model integration; it is not invoked by the endpoint.
- **`decision_engine.py`** contains general category guidance for later use; it is not invoked by the endpoint.

No OpenRouter key is needed for the current API. The `.env.example` file documents variables reserved for future model integration. Keep actual credentials in a local `.env` file, which is ignored by Git.
