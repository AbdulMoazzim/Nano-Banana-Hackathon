"""Local Trash-Net image validation and external vision fallbacks."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageFile, UnidentifiedImageError

ImageFile.LOAD_TRUNCATED_IMAGES = False
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_DIMENSION = 2048
MIN_CONFIDENCE = 0.45
MODEL_ID = "prithivMLmods/Trash-Net"
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class VisionError(Exception):
    """Base error for safe image-analysis failures."""
class ImageValidationError(VisionError):
    """The supplied bytes are too large, unsupported, or invalid."""
class VisionConfigurationError(VisionError):
    """The local model or its label mapping cannot be loaded."""
class VisionProviderError(VisionError):
    """Kept for compatibility with the existing endpoint error handling."""
class VisionResponseError(VisionError):
    """The local model returned unusable output."""

# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PreparedImage:
    data_url: str
    media_type: str
    width: int
    height: int

_MODEL_LOCK = threading.Lock()
_MODEL_BUNDLE: tuple[Any, Any, dict[int, str]] | None = None


def _validated_image(data: bytes) -> Image.Image:
    if not data:
        raise ImageValidationError("The uploaded image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError("The uploaded image exceeds the size limit.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                raise ImageValidationError("This image format is not supported.")
            if image.width < 1 or image.height < 1 or image.width * image.height > MAX_IMAGE_PIXELS:
                raise ImageValidationError("The image dimensions are invalid or too large.")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = image.convert("RGB")
            image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
            return image.copy()
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageValidationError("The uploaded file is not a valid readable image.") from exc


def prepare_image(data: bytes) -> PreparedImage:
    """Validate actual image content and produce a bounded JPEG data URL."""
    image = _validated_image(data)
    output = io.BytesIO()
    image.save(output, "JPEG", quality=85, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return PreparedImage(f"data:image/jpeg;base64,{encoded}", "image/jpeg", image.width, image.height)

# ---------------------------------------------------------------------------
# Local Trash-Net classification
# ---------------------------------------------------------------------------

def normalize_model_label(label: Any) -> str:
    """Map only Trash-Net's known labels to the existing SortWise categories."""
    value = str(label).strip().lower().replace("_", " ").replace("-", " ")
    return {
        "plastic": "plastic",
        "glass": "glass",
        "metal": "metal",
        "paper": "paper_cardboard",
        "cardboard": "paper_cardboard",
        "trash": "general",
        "general": "general",
        "mixed": "general",
        "paper/cardboard": "paper_cardboard",
        "paper cardboard": "paper_cardboard",
    }.get(value, "unknown")


def _load_local_model() -> tuple[Any, Any, dict[int, str]]:
    """Load the cached processor/model once; never download at request time."""
    global _MODEL_BUNDLE
    if _MODEL_BUNDLE is not None:
        return _MODEL_BUNDLE
    with _MODEL_LOCK:
        if _MODEL_BUNDLE is not None:
            return _MODEL_BUNDLE
        try:
            import torch
            from transformers import AutoImageProcessor, SiglipForImageClassification
            processor = AutoImageProcessor.from_pretrained(MODEL_ID, local_files_only=True)
            model = SiglipForImageClassification.from_pretrained(MODEL_ID, local_files_only=True)
            model.to("cpu")
            model.eval()
            raw_labels = getattr(model.config, "id2label", {})
            labels = {int(index): str(label) for index, label in raw_labels.items()}
            if not labels:
                raise VisionConfigurationError("Trash-Net did not expose an output-label mapping.")
            _MODEL_BUNDLE = (processor, model, labels)
            return _MODEL_BUNDLE
        except VisionError:
            raise
        except Exception as exc:
            raise VisionConfigurationError("The local Trash-Net model could not be loaded from cache.") from exc


def _classify_local(image: Image.Image) -> dict[str, Any]:
    try:
        import torch
        processor, model, labels = _load_local_model()
        inputs = processor(images=image, return_tensors="pt")
        with torch.inference_mode():
            logits = model(**inputs).logits
            probabilities = torch.softmax(logits.float(), dim=-1)[0]
        index = int(torch.argmax(probabilities).item())
        if index not in labels:
            raise VisionResponseError("Trash-Net returned an unmapped output index.")
        raw_label = labels[index]
        confidence = float(probabilities[index].item())
        category = normalize_model_label(raw_label)
        if category == "unknown" or confidence < MIN_CONFIDENCE:
            category = "unknown"
            confidence = min(confidence, 0.44)
        item_name = f"{raw_label.title()} item" if category != "unknown" else "Unidentified item"
        material = raw_label if category != "unknown" else "unknown"
        evidence = f"Local Trash-Net classified the image as {raw_label!r}."
        return {"item_name": item_name, "category": category, "material": material, "confidence": confidence, "evidence": evidence}
    except VisionError:
        raise
    except Exception as exc:
        raise VisionResponseError("Local Trash-Net inference failed.") from exc


_CLASSIFICATION_PROMPT = """\
Identify the main waste item visible in the image. Return ONLY a JSON object with:
{"item_name":"short name","category":"plastic|paper_cardboard|metal|glass|organic|general|electronic|unknown","material":"short material","confidence":0.0,"evidence":"brief visible evidence"}
Use only these categories. Confidence is an estimate, not a verified probability. If uncertain, mixed, obscured, or unsupported, use category "unknown" and confidence below 0.45. Do not provide disposal guidance.
"""


def _extract_classification_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise VisionResponseError("OpenRouter classification returned no JSON object.")
    try:
        raw = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise VisionResponseError("OpenRouter classification returned invalid JSON.") from exc
    if not isinstance(raw, dict):
        raise VisionResponseError("OpenRouter classification was not a JSON object.")
    item_name = raw.get("item_name")
    material = raw.get("material")
    evidence = raw.get("evidence")
    confidence = raw.get("confidence")
    if not all(isinstance(value, str) and value.strip() for value in (item_name, material, evidence)):
        raise VisionResponseError("OpenRouter classification omitted required text fields.")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise VisionResponseError("OpenRouter classification confidence was invalid.")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise VisionResponseError("OpenRouter classification confidence was out of range.")
    category = normalize_model_label(raw.get("category", "unknown"))
    if category == "unknown" or confidence < MIN_CONFIDENCE:
        return {"item_name": "Unidentified item", "category": "unknown", "material": "unknown", "confidence": min(confidence, 0.44), "evidence": evidence.strip()}
    return {"item_name": item_name.strip(), "category": category, "material": material.strip(), "confidence": confidence, "evidence": evidence.strip()}



def _openrouter_model_chain() -> tuple[str, ...]:
    primary = os.environ.get("OPENROUTER_MODEL", _PRIMARY_MODEL_DEFAULT).strip() or _PRIMARY_MODEL_DEFAULT
    configured = [model.strip() for model in os.environ.get("OPENROUTER_FALLBACK_MODELS", "").split(",") if model.strip()]
    if configured:
        fallbacks = [model for model in configured if model in _VERIFIED_FALLBACK_MODELS]
        for model in configured:
            if model not in _VERIFIED_FALLBACK_MODELS:
                logger.warning("Ignoring unverified OpenRouter fallback model: %s", model)
    else:
        fallbacks = list(_VERIFIED_FALLBACK_MODELS)
    models: list[str] = []
    for model in [primary, *fallbacks]:
        if model and model not in models:
            models.append(model)
    return tuple(models)


async def _local_classification_fallback(image: Image.Image) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_classify_local, image)
    except VisionError:
        raise
    except Exception as exc:
        raise VisionResponseError("Local Trash-Net inference failed.") from exc


async def analyze_image(data: bytes, description: str | None = None) -> dict[str, Any]:
    """Try OpenRouter, then Gemini, then local Trash-Net once."""
    image = _validated_image(data)
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    prepared = prepare_image(data)
    context = f"\nAdditional user context: {description.strip()}" if description and description.strip() else ""
    last_error: Exception | None = None
    if api_key:
        for model in _openrouter_model_chain():
            try:
                raw_text = await _call_openrouter_prompt(
                    api_key, model, prepared.data_url, _CLASSIFICATION_PROMPT + context,
                    "OPENROUTER_CLASSIFICATION_MAX_TOKENS", 256, "classification",
                )
                result = _extract_classification_json(raw_text)
                return result
            except ImageValidationError:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning("OpenRouter classification model failed (%s): model=%s; trying next configured model.", type(exc).__name__, model)
    else:
        logger.debug("analyze_image: OPENROUTER_API_KEY not set; trying Gemini if configured.")

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    gemini_model = os.environ.get("GEMINI_MODEL", _GEMINI_DEFAULT_MODEL).strip() or _GEMINI_DEFAULT_MODEL
    if gemini_key:
        try:
            raw_text = await _call_gemini_prompt(
                gemini_key, gemini_model, prepared.data_url,
                _CLASSIFICATION_PROMPT + context,
                "GEMINI_CLASSIFICATION_MAX_TOKENS", 256, "classification",
            )
            return _extract_classification_json(raw_text)
        except ImageValidationError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning("Gemini classification failed (%s): model=%s; using local fallback.", type(exc).__name__, gemini_model)

    try:
        return await _local_classification_fallback(image)
    except VisionError:
        raise
    except Exception as exc:
        raise VisionResponseError("OpenRouter and local classification failed.") from (last_error or exc)
# ---------------------------------------------------------------------------
# OpenRouter condition assessment
# ---------------------------------------------------------------------------

_OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_PRIMARY_MODEL_DEFAULT = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
_VERIFIED_FALLBACK_MODELS = (
    "dots-studio/dots-3-note-preview:free",
    "thinkingmachines/inkling-small:free",
)
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
_GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_CONDITION_FIELDS = ("cracks_fractures", "holes_leaks_breakage", "severe_deformation")
_VALID_STATUSES = frozenset({"not_detected", "detected", "unable_to_assess"})
_VALID_CONDITION_TYPES = frozenset(_CONDITION_FIELDS)
_RATE_LIMIT_HEADERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")

_CONDITION_PROMPT = """\
You are a visual damage inspector. Examine only what is DIRECTLY VISIBLE in this image.

Assess each condition INDEPENDENTLY:
- cracks_fractures: visible cracks, fractures, or hairline splits on the surface
- holes_leaks_breakage: visible holes, punctures, leaks, or broken-off components
- severe_deformation: visible severe crushing, collapse, or structural distortion

Rules you MUST follow:
1. Report only what is directly visible. Do not infer hidden structural damage.
2. A dent or minor indent is NOT a crack. Do not conflate them.
3. Assess each condition independently. Do not mark a condition unable_to_assess \
merely because another part of the image is obscured.
4. Set image_unclear to true only when overall image quality meaningfully limits the entire assessment.
5. Do not generate disposal instructions.
6. For every condition with status "detected", add one entry to "findings" with the \
condition_type and a single sentence of visual_evidence quoting what you see.
7. If a condition cannot be determined for that specific aspect, use "unable_to_assess" for that field only.

Respond with ONLY a valid JSON object â€” no markdown fences, no text outside the object:
{
  "cracks_fractures": "not_detected" | "detected" | "unable_to_assess",
  "holes_leaks_breakage": "not_detected" | "detected" | "unable_to_assess",
  "severe_deformation": "not_detected" | "detected" | "unable_to_assess",
  "image_unclear": true | false,
  "findings": [
    {"condition_type": "...", "visual_evidence": "..."}
  ]
}"""


def _safe_fallback_condition() -> dict[str, Any]:
    """Return a condition dict with all fields set to unable_to_assess."""
    return {
        "cracks_fractures": "unable_to_assess",
        "holes_leaks_breakage": "unable_to_assess",
        "severe_deformation": "unable_to_assess",
        "image_unclear": True,
        "findings": [],
    }


def _extract_condition_json(text: str) -> dict[str, Any]:
    """Strip reasoning blocks and markdown fences, then parse and validate the JSON.

    Raises ValueError with a sanitized message if the response is malformed,
    contains unsupported values, or is internally contradictory.
    """
    # Remove <think>â€¦</think> blocks produced by reasoning models
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip optional markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in condition response.")

    try:
        raw = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Condition response is not valid JSON: {exc.msg}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Condition response is not a JSON object.")

    # Validate condition status fields
    for field in _CONDITION_FIELDS:
        val = raw.get(field)
        if val not in _VALID_STATUSES:
            raise ValueError(
                f"Condition field {field!r} has unsupported value "
                f"{val!r}; expected one of {sorted(_VALID_STATUSES)}."
            )

    # Validate image_unclear
    if not isinstance(raw.get("image_unclear"), bool):
        raise ValueError("Condition field 'image_unclear' must be a boolean.")

    # Validate findings
    findings_raw = raw.get("findings")
    if not isinstance(findings_raw, list):
        raise ValueError("Condition field 'findings' must be a list.")

    validated_findings: list[dict[str, str]] = []
    for i, entry in enumerate(findings_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"findings[{i}] is not an object.")
        ct = entry.get("condition_type")
        ev = entry.get("visual_evidence")
        if ct not in _VALID_CONDITION_TYPES:
            raise ValueError(
                f"findings[{i}].condition_type {ct!r} is not one of {sorted(_VALID_CONDITION_TYPES)}."
            )
        if not isinstance(ev, str) or not ev.strip():
            raise ValueError(f"findings[{i}].visual_evidence must be a non-empty string.")
        validated_findings.append({"condition_type": ct, "visual_evidence": ev.strip()})

    # Consistency check: every "detected" field must have a matching finding
    for field in _CONDITION_FIELDS:
        if raw[field] == "detected":
            has_finding = any(f["condition_type"] == field for f in validated_findings)
            if not has_finding:
                raise ValueError(
                    f"Condition field {field!r} is 'detected' but has no corresponding finding."
                )

    return {
        "cracks_fractures": raw["cracks_fractures"],
        "holes_leaks_breakage": raw["holes_leaks_breakage"],
        "severe_deformation": raw["severe_deformation"],
        "image_unclear": raw["image_unclear"],
        "findings": validated_findings,
    }


def _condition_endpoint() -> str:
    endpoint = os.environ.get("OPENROUTER_CHAT_ENDPOINT", "").strip()
    if endpoint:
        return endpoint
    base_url = os.environ.get("OPENROUTER_BASE_URL", _OPENROUTER_DEFAULT_BASE_URL).strip()
    return f"{base_url.rstrip('/')}/chat/completions"


def _condition_setting(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        logger.warning("Invalid %s; using the safe default.", name)
        return default
    return min(max(value, minimum), maximum)


def _sanitize_provider_text(value: str, limit: int = 240) -> str:
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", value)
    text = re.sub(r"(?i)(api[_-]?key|authorization)\s*[:=]\s*[^,\s}]+", r"\1=[redacted]", text)
    text = " ".join(text.split())
    return text[:limit] + ("â€¦" if len(text) > limit else "")


def _sanitize_provider_body(response: Any) -> str:
    try:
        body = response.json()
    except Exception:
        return _sanitize_provider_text(getattr(response, "text", "")) or "<empty body>"
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            details = {key: error[key] for key in ("code", "type", "message") if key in error}
            metadata = error.get("metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("error_type"), str):
                details["error_type"] = metadata["error_type"]
            if details:
                return _sanitize_provider_text(json.dumps(details, ensure_ascii=True))
    return _sanitize_provider_text(json.dumps(body, ensure_ascii=True))


def _safe_rate_limit_headers(headers: Any) -> dict[str, str]:
    return {name: str(headers[name]) for name in _RATE_LIMIT_HEADERS if name in headers}


def _extract_message_content(body: Any) -> str:
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        raise VisionResponseError("OpenRouter condition response did not contain a 'choices' array.")
    message = choices[0].get("message", {})
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str))
    return ""


def _extract_gemini_content(body: Any) -> str:
    if not isinstance(body, dict):
        raise VisionResponseError("Gemini response was not a JSON object.")
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise VisionResponseError("Gemini response did not contain candidates.")
    content = candidates[0].get("content", {})
    parts = content.get("parts", []) if isinstance(content, dict) else []
    if not isinstance(parts, list):
        raise VisionResponseError("Gemini response parts were invalid.")
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))
    if not text.strip():
        raise VisionResponseError("Gemini returned empty content.")
    return text


def _gemini_endpoint(model: str) -> str:
    return f"{_GEMINI_DEFAULT_BASE_URL}/models/{model}:generateContent"


async def _call_gemini_prompt(
    api_key: str,
    model: str,
    data_url: str,
    prompt: str,
    max_tokens_name: str,
    default_max_tokens: int,
    operation: str,
) -> str:
    """Call Gemini with the same bounded JPEG and task prompt used by OpenRouter."""
    import httpx

    try:
        media_header, encoded_image = data_url.split(",", 1)
        media_type = media_header.removeprefix("data:").split(";", 1)[0]
        if media_type != "image/jpeg" or not encoded_image:
            raise ValueError("unsupported image data URL")
    except (ValueError, AttributeError) as exc:
        raise VisionResponseError("Gemini image payload could not be prepared.") from exc

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": media_type, "data": encoded_image}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": int(_condition_setting(max_tokens_name, default_max_tokens, 64, 1024)),
            "responseMimeType": "application/json",
        },
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_condition_setting("GEMINI_TIMEOUT_SECONDS", 20.0, 5.0, 60.0)) as client:
            response = await client.post(
                _gemini_endpoint(model),
                json=payload,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            )
    except Exception as exc:
        logger.warning("Gemini %s request failed (%s) after %.2fs: %s", operation, type(exc).__name__, time.perf_counter() - started, _sanitize_provider_text(str(exc)) or "no detail")
        raise

    elapsed = time.perf_counter() - started
    logger.info("Gemini %s response: HTTP %s in %.2fs", operation, response.status_code, elapsed)
    if response.status_code != 200:
        logger.warning("Gemini %s provider error: HTTP %s; body=%s", operation, response.status_code, _sanitize_provider_body(response))
        raise VisionProviderError(f"Gemini returned HTTP {response.status_code}.")
    try:
        body = response.json()
    except ValueError as exc:
        raise VisionResponseError("Gemini response was not valid JSON.") from exc
    if isinstance(body, dict) and body.get("error"):
        logger.warning("Gemini %s returned an error object: model=%s elapsed=%.2fs details=%s", operation, model, elapsed, _sanitize_provider_body(response))
        raise VisionProviderError("Gemini returned an error object.")
    if not isinstance(body, dict) or not body.get("candidates"):
        logger.warning("Gemini %s returned an unexpected response: model=%s elapsed=%.2fs details=%s", operation, model, elapsed, _sanitize_provider_body(response))
    return _extract_gemini_content(body)


async def _call_openrouter_prompt(api_key: str, model: str, data_url: str, prompt: str, max_tokens_name: str, default_max_tokens: int, operation: str = "condition") -> str:
    """POST to OpenRouter and return the raw text content of the first choice."""
    import httpx

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": int(_condition_setting(max_tokens_name, default_max_tokens, 64, 1024)),
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/SortWise-AI",
        "X-Title": "SortWise AI",
    }

    timeout_seconds = _condition_setting("OPENROUTER_CONDITION_TIMEOUT_SECONDS", 20.0, 5.0, 60.0)
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(_condition_endpoint(), json=payload, headers=headers)
    except Exception as exc:
        logger.warning("OpenRouter condition request failed (%s) after %.2fs: %s", type(exc).__name__, time.perf_counter() - started, _sanitize_provider_text(str(exc)) or "no detail")
        raise

    logger.info("OpenRouter %s response: HTTP %s in %.2fs", operation, response.status_code, time.perf_counter() - started)

    if response.status_code != 200:
        logger.warning("OpenRouter %s provider error: HTTP %s; body=%s; rate_limit_headers=%s", operation, response.status_code, _sanitize_provider_body(response), _safe_rate_limit_headers(response.headers))
        raise VisionProviderError(
            f"OpenRouter returned HTTP {response.status_code} for condition assessment."
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise VisionResponseError("OpenRouter condition response was not valid JSON.") from exc
    if not isinstance(body, dict) or "choices" not in body or not body.get("choices"):
        logger.warning(
            "OpenRouter %s returned an unexpected response: model=%s elapsed=%.2fs details=%s",
            operation, model, time.perf_counter() - started, _sanitize_provider_body(response),
        )
    content = _extract_message_content(body)
    if not content:
        raise VisionResponseError("OpenRouter returned an empty condition response.")
    return content


async def _call_openrouter(api_key: str, model: str, data_url: str) -> str:
    return await _call_openrouter_prompt(api_key, model, data_url, _CONDITION_PROMPT, "OPENROUTER_CONDITION_MAX_TOKENS", 256, "condition")


async def assess_condition(
    data: bytes,
    description: str | None = None,
) -> dict[str, Any]:
    """Assess conditions with each configured OpenRouter model once, then fall back safely."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    started = time.perf_counter()
    try:
        prepared = prepare_image(data)
    except ImageValidationError:
        raise

    if api_key:
        for model in _openrouter_model_chain():
            try:
                raw_text = await _call_openrouter(api_key, model, prepared.data_url)
                parsed = _extract_condition_json(raw_text)
                logger.info("Condition assessment completed with model=%s in %.2fs.", model, time.perf_counter() - started)
                return parsed
            except ImageValidationError:
                raise
            except Exception as exc:
                logger.warning("OpenRouter condition model failed (%s): model=%s; trying next configured model.", type(exc).__name__, model)
    else:
        logger.debug("assess_condition: OPENROUTER_API_KEY not set; trying Gemini if configured.")

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    gemini_model = os.environ.get("GEMINI_MODEL", _GEMINI_DEFAULT_MODEL).strip() or _GEMINI_DEFAULT_MODEL
    if gemini_key:
        try:
            raw_text = await _call_gemini_prompt(
                gemini_key, gemini_model, prepared.data_url, _CONDITION_PROMPT,
                "GEMINI_CONDITION_MAX_TOKENS", 256, "condition",
            )
            parsed = _extract_condition_json(raw_text)
            logger.info("Condition assessment completed with Gemini model=%s in %.2fs.", gemini_model, time.perf_counter() - started)
            return parsed
        except ImageValidationError:
            raise
        except Exception as exc:
            logger.warning("Gemini condition model failed (%s): model=%s; returning unable_to_assess.", type(exc).__name__, gemini_model)

    logger.warning("All external condition models failed after %.2fs; returning unable_to_assess.", time.perf_counter() - started)
    return _safe_fallback_condition()
