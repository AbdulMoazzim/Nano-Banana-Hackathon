# SortWise AI Backend

SortWise AI is a FastAPI waste-identification and sorting assistant. It accepts an image and optional user description, identifies the visible waste item, assesses visible damage when possible, and returns deterministic, general disposal guidance. The service does not invent local recycling rules: users are directed to check their local waste authority.

## Core features

- Validates the uploaded file's actual image contents, format, byte size, dimensions, and readability.
- Safely converts supported images to bounded JPEG data for external vision providers.
- Classifies waste with an external-provider fallback chain and a cached local Trash-Net fallback.
- Assesses visible cracks/fractures, holes/leaks/breakage, and severe deformation independently.
- Uses Python's deterministic decision engine as the only source of disposal guidance, preparation steps, and warnings.
- Preserves conservative uncertainty handling: unreliable identification becomes `unknown`, and unavailable condition assessment becomes `unable_to_assess`.

## Architecture and request flow

```text
multipart/form-data upload
        |
        v
app.py: read bounded upload and pass image + description
        |
        v
vision.py: validate image -> resize/encode -> external classification
        |                                      |
        |                                      +--> OpenRouter model chain
        |                                      +--> Gemini API
        |                                      +--> local Trash-Net (once)
        |
        +--> independent condition-assessment chain
        |       OpenRouter -> Gemini -> unable_to_assess
        |
        v
vision.py: parse and validate model output
        |
        v
app.py: decision_engine.decision_for(category)
        |
        v
schemas.py: validate and serialize the final AnalysisResponse
```

Classification order is:

1. Nemotron through OpenRouter: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`
2. Dots through OpenRouter: `dots-studio/dots-3-note-preview:free`
3. Gemma through OpenRouter: `google/gemma-4-26b-a4b-it:free`
4. Gemini API: the model in `GEMINI_MODEL` (default `gemini-2.5-flash`)
5. Local `prithivMLmods/Trash-Net` once, if its cached checkpoint is available; otherwise the endpoint returns a safe `unknown` result.

The OpenRouter fallback list is configurable, but `vision.py` only accepts the verified fallback IDs above. A valid model response whose validated category is `unknown` stops classification immediately; it does not trigger another model. Provider errors, timeouts, malformed JSON, missing content, and invalid fields continue to the next fallback. Confidence is an estimate, not a calibrated probability; values below the 0.45 threshold become `unknown`.

Condition assessment has its own independent external chain. It uses the configured OpenRouter models first and Gemini last. A valid condition response is returned after schema and consistency checks. If every configured provider fails, the response contains `unable_to_assess` for each condition and `image_unclear: true`; it must never imply that an item is undamaged. Condition failures do not fail an otherwise valid analysis request.

### Module responsibilities

- `app.py`: defines the FastAPI application, health routes, multipart endpoint, bounded upload read, safe vision fallback, orchestration, and final response construction. It passes the selected category to the decision engine and never accepts model disposal instructions.
- `vision.py`: validates and preprocesses images; calls OpenRouter and Gemini with the task-specific vision prompts; parses, normalizes, and validates classification/condition data; loads cached Trash-Net locally; and logs sanitized provider diagnostics.
- `schemas.py`: defines the public Pydantic response contract, supported category literals, condition statuses, and condition finding types.
- `decision_engine.py`: normalizes category aliases and deterministically generates `disposal_guidance`, `preparation_steps`, and `warnings`.
- `tests/`: focused unit and endpoint tests. External calls and local model loading are mocked, so tests do not require API keys or model downloads.
- `tools/`: standalone local-model and live-endpoint evaluation utilities. `eval_condition.py` loads the project `.env` for evaluation, submits real requests to a running server, and compares only against explicitly supplied manifest expectations.

## API contract

### `POST /api/v1/analyses`

The endpoint accepts `multipart/form-data`:

- `image`: required image file.
- `description`: optional text describing the item or context.

Example:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/analyses `
  -F "image=@sample.jpg" `
  -F "description=Empty glass jar"
```

Successful responses are HTTP `200` and have this shape:

```json
{
  "request_id": "uuid",
  "status": "completed",
  "result": {
    "item_name": "Glass jar",
    "category": "glass",
    "material": "glass",
    "confidence": 0.86,
    "evidence": "A transparent cylindrical glass container is visible.",
    "disposal_guidance": "Separate by local rules; some programs accept glass containers while others do not.",
    "preparation_steps": [
      "Empty and rinse when practical.",
      "Handle broken glass carefully."
    ],
    "warnings": [
      "Local disposal rules vary; check your local waste authority's guidance."
    ],
    "condition": {
      "cracks_fractures": "not_detected",
      "holes_leaks_breakage": "not_detected",
      "severe_deformation": "not_detected",
      "image_unclear": false,
      "findings": []
    }
  }
}
```

`category` is one of `plastic`, `paper_cardboard`, `metal`, `glass`, `organic`, `general`, `electronic`, or `unknown`. The condition object may be `null` if construction fails; provider uncertainty is represented by its `unable_to_assess` statuses. The endpoint has no polling operation and returns synchronously.

## Image handling and safety

Supported formats are JPEG, PNG, WEBP, and GIF. Uploads are limited to 10 MiB and 20 million pixels. Pillow verifies actual image content, rejects corrupt or unsupported files, prevents decompression-bomb dimensions, and resizes the longest dimension to at most 2048 pixels before JPEG encoding. The endpoint reads only one byte beyond the configured upload limit so oversized files can be rejected safely.

Trash-Net has six labels: `cardboard`, `glass`, `metal`, `paper`, `plastic`, and `trash`. They map conservatively to the existing categories; `paper`/`cardboard` map to `paper_cardboard`, and `trash` maps to `general`. Trash-Net does not identify organic or electronic waste reliably. Unmapped labels, low-confidence results, failed inference, obscured images, and unsupported items must not be presented as confident classifications.

## Configuration

Copy `.env.example` to `.env` and fill in credentials locally. Never commit `.env` or place keys in source, tests, README examples, logs, or responses. The application reads environment variables from its process; it does not automatically load `.env` itself. Export the variables before starting Uvicorn, or use a process/environment loader appropriate to your shell. The evaluation tools load the project `.env` themselves.

OpenRouter settings:

```text
OPENROUTER_API_KEY=
OPENROUTER_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_CHAT_ENDPOINT=https://openrouter.ai/api/v1/chat/completions
OPENROUTER_FALLBACK_MODELS=dots-studio/dots-3-note-preview:free,google/gemma-4-26b-a4b-it:free
OPENROUTER_CONDITION_TIMEOUT_SECONDS=20
OPENROUTER_CONDITION_MAX_TOKENS=256
OPENROUTER_CLASSIFICATION_MAX_TOKENS=256
```

Gemini settings:

```text
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_TIMEOUT_SECONDS=20
GEMINI_CLASSIFICATION_MAX_TOKENS=256
GEMINI_CONDITION_MAX_TOKENS=256
```

`gemini-2.5-flash` is the verified default for image input and structured JSON output. The adapter uses Google's `generateContent` endpoint, sends the bounded JPEG as inline image data, sends the same classification or condition prompt used by the pipeline, and requests `application/json` output. If a provider does not return usable content, existing parsing and validation decide whether to continue or fall back safely.

## Install and run

Use Python 3.10 or newer from this directory (`Nano-Banana-Hackathon/SortWise`):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app:app --reload
```

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `/docs` and health check at `/health`. The local Trash-Net checkpoint must already be available in the Hugging Face cache for offline local fallback. The application uses `local_files_only=True` and never downloads weights during an API request.

## Tests and evaluation

Run the complete offline suite:

```powershell
python -m pytest -q
```

Run the local Trash-Net smoke test. This standalone tool may download the pretrained checkpoint once if it is not cached; it does not download the TrashNet dataset or train a model:

```powershell
python tools\test_trash_net.py path\to\image.webp
```

For a real end-to-end request, start the server in one terminal, then run the evaluator in another. It loads `.env`, submits images to `POST /api/v1/analyses`, and reports classification, confidence, conditions, findings, status, and latency:

```powershell
python tools\eval_condition.py --manifest tools\eval_manifest.json
python tools\eval_condition.py path\to\image.webp
```

The manifest contains optional human-provided expectations. Two images are not an accuracy evaluation; real-world accuracy requires a labelled evaluation set. `tools\test_openrouter_vision.py` is an optional direct OpenRouter smoke test and is not a substitute for the full FastAPI evaluation.

## Error handling and limitations

- Invalid, corrupt, oversized, or unsupported images return a client error from the API.
- Vision provider failures are sanitized in logs and never expose authorization headers, API keys, image data, or raw sensitive requests.
- A classification failure falls back to the next provider, then local Trash-Net, then the endpoint's safe `unknown` result.
- A condition failure falls back independently and ultimately returns `unable_to_assess`; it never claims the item is intact.
- Disposal text is always deterministic Python output. It is general guidance, not a local authority ruling.
- Provider rate limits, capacity failures, timeouts, model availability, and latency can vary, especially for free models.
- Model confidence is an estimate and is not measured accuracy. Trash-Net's class limitations and known image ambiguity can produce wrong or unknown classifications.

### Adding or changing a model safely

1. Verify the exact model ID, image-input support, output format, and provider limits from authoritative documentation.
2. Keep provider request construction in `vision.py`; reuse the existing bounded image payload and task prompt.
3. Reuse the existing parsing, category normalization, confidence threshold, and safe fallback behavior.
4. Add mocked tests for success, provider failure, malformed/invalid output, ordering, and missing configuration.
5. Do not let a model generate disposal guidance, change schemas, lower uncertainty thresholds, or add a model to the verified fallback list without evidence and review.
6. Run `python -m pytest -q` and `git diff --check`. Live tests require explicit credentials and should never be repeated automatically.

## Instructions for AI Coding Assistants

Before changing code, inspect the relevant implementation, schemas, tests, configuration, and Git diff. Preserve `POST /api/v1/analyses`, its request fields, response fields, category literals, safe fallbacks, and the deterministic disposal engine. Reuse the existing `httpx`, Pillow, PyTorch, and Transformers dependencies instead of adding alternatives unnecessarily. Keep image preprocessing, provider calls, parsing, and disposal decisions modular. Add focused mocked tests for behavior changes, run the full suite, and report actual results.

Never print, expose, stage, or commit `.env`, API keys, authorization headers, base64 image data, or sensitive provider responses. Do not claim a live integration or real-world model accuracy from unit tests; live behavior requires a successful request, and accuracy requires labelled evaluation data. Avoid unrelated refactoring, frontend changes, model downloads, training, automatic retry loops, force-pushes, and history rewrites.

## Container deployment

The included Dockerfile builds the API with Python 3.11, installs the dependency ranges, and preloads prithivMLmods/Trash-Net into /opt/huggingface during the image build. Runtime model loading remains local-only, so rebuild the image when model or dependency versions change.

Build and run locally:

~~~powershell
docker build -t sortwise-api .
docker run --rm -p 8000:8000 -e FRONTEND_ORIGIN=https://your-frontend.example -e OPENROUTER_API_KEY= -e GEMINI_API_KEY= sortwise-api
~~~

The backend needs enough disk for PyTorch, Transformers, and the Trash-Net checkpoint, plus enough RAM and startup time for CPU model loading. A small/free serverless plan may not support this workload reliably; use a persistent container service or VM with adequate memory. Do not deploy until the image build and /health check succeed.

Set FRONTEND_ORIGIN to the exact browser origin, without a trailing path, such as https://sortwise.example.com. Set the frontend build variable NEXT_PUBLIC_API_URL to the backend base URL, such as https://api.sortwise.example.com. Do not include /api/v1/analyses in that variable.
