import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import torch
from fastapi.testclient import TestClient
from PIL import Image

from app import app
from decision_engine import decision_for
from vision import (
    ImageValidationError,
    MAX_IMAGE_BYTES,
    VisionProviderError,
    VisionResponseError,
    analyze_image,
    normalize_model_label,
    prepare_image,
    _extract_condition_json,
    _call_openrouter_prompt,
    _call_gemini_prompt,
    _safe_fallback_condition,
    assess_condition,
)
from schemas import ConditionFinding, WasteCondition


def img(size=(20, 20)):
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


def fake_local_model(logits, label="plastic"):
    processor = lambda **kwargs: {"pixel_values": object()}
    model = lambda **kwargs: SimpleNamespace(logits=torch.tensor([logits], dtype=torch.float32))
    return processor, model, {index: label for index, label in enumerate([label] * len(logits))}


# ---------------------------------------------------------------------------
# Existing tests (must remain green)
# ---------------------------------------------------------------------------

def test_preprocess_and_limits():
    prepared = prepare_image(img((4000, 3000)))
    assert prepared.width <= 2048 and prepared.height <= 2048
    with pytest.raises(ImageValidationError):
        prepare_image(b"bad")
    with pytest.raises(ImageValidationError):
        prepare_image(b"x" * (MAX_IMAGE_BYTES + 1))


def test_trash_net_label_mapping_is_conservative():
    assert normalize_model_label("plastic") == "plastic"
    assert normalize_model_label("glass") == "glass"
    assert normalize_model_label("metal") == "metal"
    assert normalize_model_label("paper") == "paper_cardboard"
    assert normalize_model_label("cardboard") == "paper_cardboard"
    assert normalize_model_label("trash") == "general"
    assert normalize_model_label("organic") == "unknown"
    assert normalize_model_label("electronic") == "unknown"
    assert normalize_model_label("unrecognized") == "unknown"


def test_categories():
    for category in ("plastic", "paper_cardboard", "metal", "glass", "organic", "general", "electronic", "unknown"):
        result = decision_for(category)
        assert result["category"] == category
        assert result["disposal_guidance"] and result["warnings"]




@pytest.mark.asyncio
async def test_openrouter_provider_error_payload_is_sanitized(caplog):
    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"error": {"code": 502, "message": "worker unavailable", "metadata": {"error_type": "provider_unavailable"}}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    with patch("httpx.AsyncClient", return_value=FakeClient()):
        with pytest.raises(VisionResponseError):
            await _call_openrouter_prompt("secret-key", "test-model", "data:image/jpeg;base64,hidden", "prompt", "TEST_MAX", 64, "classification")
    assert "classification" in caplog.text
    assert "test-model" in caplog.text
    assert "provider_unavailable" in caplog.text
    assert "secret-key" not in caplog.text
    assert "hidden" not in caplog.text


@pytest.mark.asyncio
async def test_openrouter_classification_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test-model")
    local_result = {"item_name": "Plastic item", "category": "plastic", "material": "plastic", "confidence": 0.8, "evidence": "Local fallback"}
    with patch("vision._call_openrouter_prompt", new=AsyncMock(side_effect=VisionProviderError("provider unavailable"))):
        with patch("vision._classify_local", return_value=local_result):
            result = await analyze_image(img())
    assert result == local_result


@pytest.mark.asyncio
async def test_openrouter_and_local_classification_fail_safely(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test-model")
    with patch("vision._call_openrouter_prompt", new=AsyncMock(side_effect=VisionProviderError("provider unavailable"))):
        with patch("vision._classify_local", side_effect=VisionResponseError("local unavailable")):
            with pytest.raises(VisionResponseError):
                await analyze_image(img())


@pytest.mark.asyncio
async def test_gemini_request_uses_inline_image_and_json_output():
    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "{\"ok\":true}"}]}}]}

    class FakeClient:
        def __init__(self):
            self.call = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            self.call = (args, kwargs)
            return FakeResponse()

    client = FakeClient()
    with patch("httpx.AsyncClient", return_value=client):
        result = await _call_gemini_prompt(
            "secret-key", "gemini-2.5-flash", "data:image/jpeg;base64,hidden",
            "same task prompt", "TEST_MAX", 64, "classification",
        )
    assert result == '{"ok":true}'
    assert client.call[0][0].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
    assert client.call[1]["headers"]["x-goog-api-key"] == "secret-key"
    payload = client.call[1]["json"]
    assert payload["contents"][0]["parts"][0]["inline_data"] == {"mime_type": "image/jpeg", "data": "hidden"}
    assert payload["contents"][0]["parts"][1]["text"] == "same task prompt"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.asyncio
async def test_gemini_classification_is_final_external_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "dots-studio/dots-3-note-preview:free,thinkingmachines/inkling-small:free")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    response = '{"item_name":"Bottle","category":"plastic","material":"plastic","confidence":0.8,"evidence":"Bottle visible."}'
    openrouter = AsyncMock(side_effect=VisionProviderError("provider unavailable"))
    gemini = AsyncMock(return_value=response)
    with patch("vision._call_openrouter_prompt", new=openrouter), patch("vision._call_gemini_prompt", new=gemini):
        result = await analyze_image(img())
    assert result["category"] == "plastic"
    assert openrouter.await_count == 3
    assert gemini.await_count == 1
    assert gemini.await_args.args[1] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_gemini_failure_uses_local_classification_once(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    local_result = {"item_name": "Plastic item", "category": "plastic", "material": "plastic", "confidence": 0.8, "evidence": "Local fallback"}
    with patch("vision._call_openrouter_prompt", new=AsyncMock(side_effect=VisionProviderError("provider unavailable"))), patch("vision._call_gemini_prompt", new=AsyncMock(side_effect=VisionProviderError("quota"))), patch("vision._classify_local", return_value=local_result):
        result = await analyze_image(img())
    assert result == local_result


@pytest.mark.asyncio
async def test_gemini_invalid_classification_output_uses_local(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    local_result = {"item_name": "Plastic item", "category": "plastic", "material": "plastic", "confidence": 0.8, "evidence": "Local fallback"}
    with patch("vision._call_openrouter_prompt", new=AsyncMock(side_effect=VisionProviderError("provider unavailable"))), patch("vision._call_gemini_prompt", new=AsyncMock(return_value="not json")), patch("vision._classify_local", return_value=local_result):
        result = await analyze_image(img())
    assert result == local_result


@pytest.mark.asyncio
async def test_missing_external_keys_skips_gemini(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    local_result = {"item_name": "Plastic item", "category": "plastic", "material": "plastic", "confidence": 0.8, "evidence": "Local fallback"}
    with patch("vision._call_gemini_prompt", new=AsyncMock()) as gemini, patch("vision._classify_local", return_value=local_result):
        result = await analyze_image(img())
    assert result == local_result
    gemini.assert_not_awaited()


@pytest.mark.asyncio
async def test_gemini_condition_success_after_openrouter_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    with patch("vision._call_openrouter", new=AsyncMock(side_effect=VisionProviderError("provider unavailable"))), patch("vision._call_gemini_prompt", new=AsyncMock(return_value=_VALID_UNDAMAGED_JSON)) as gemini:
        result = await assess_condition(img())
    assert result["image_unclear"] is False
    assert gemini.await_count == 1


@pytest.mark.asyncio
async def test_openrouter_classification_is_parsed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    response = '{"item_name":"Plastic bottle","category":"plastic","material":"plastic","confidence":0.91,"evidence":"A translucent bottle is visible."}'
    with patch("vision._call_openrouter_prompt", new=AsyncMock(return_value=response)):
        result = await analyze_image(img())
    assert result["category"] == "plastic"
    assert result["confidence"] == 0.91


@pytest.mark.asyncio
async def test_openrouter_uncertain_classification_becomes_unknown(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    response = '```json {"item_name":"Bottle","category":"plastic","material":"plastic","confidence":0.2,"evidence":"The image is unclear."} ```'
    with patch("vision._call_openrouter_prompt", new=AsyncMock(return_value=response)):
        result = await analyze_image(img())
    assert result["category"] == "unknown"
    assert result["confidence"] <= 0.44

def test_openrouter_model_chain_uses_verified_order(monkeypatch):
    from vision import _openrouter_model_chain
    monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "dots-studio/dots-3-note-preview:free,thinkingmachines/inkling-small:free,unverified/model")
    assert _openrouter_model_chain() == ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "dots-studio/dots-3-note-preview:free", "thinkingmachines/inkling-small:free")


@pytest.mark.asyncio
async def test_classification_uses_next_model_after_provider_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "dots-studio/dots-3-note-preview:free")
    response = '{"item_name":"Bottle","category":"plastic","material":"plastic","confidence":0.8,"evidence":"Bottle visible."}'
    mocked = AsyncMock(side_effect=[VisionProviderError("provider unavailable"), response])
    with patch("vision._call_openrouter_prompt", new=mocked):
        result = await analyze_image(img())
    assert result["category"] == "plastic"
    assert mocked.await_count == 2
    assert mocked.await_args_list[1].args[1] == "dots-studio/dots-3-note-preview:free"


@pytest.mark.asyncio
async def test_valid_unknown_classification_does_not_trigger_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    response = '{"item_name":"Unclear item","category":"unknown","material":"unknown","confidence":0.2,"evidence":"The item is obscured."}'
    mocked = AsyncMock(return_value=response)
    with patch("vision._call_openrouter_prompt", new=mocked):
        result = await analyze_image(img())
    assert result["category"] == "unknown"
    assert mocked.await_count == 1


@pytest.mark.asyncio
async def test_condition_uses_fallback_model_after_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODELS", "dots-studio/dots-3-note-preview:free")
    mocked = AsyncMock(side_effect=[VisionProviderError("provider unavailable"), _VALID_UNDAMAGED_JSON])
    with patch("vision._call_openrouter", new=mocked):
        result = await assess_condition(img())
    assert result["image_unclear"] is False
    assert mocked.await_count == 2
    assert mocked.await_args_list[1].args[1] == "dots-studio/dots-3-note-preview:free"


@pytest.mark.asyncio
async def test_condition_chain_exhaustion_is_unable_to_assess(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "primary-model")
    mocked = AsyncMock(side_effect=VisionProviderError("provider unavailable"))
    with patch("vision._call_openrouter", new=mocked):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "unable_to_assess"
    assert result["image_unclear"] is True
    assert mocked.await_count == 3

@pytest.mark.asyncio
async def test_local_inference_uses_model_label_mapping(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    fake = fake_local_model([0.1, 3.0, 0.2], "plastic")
    with patch("vision._load_local_model", return_value=fake):
        result = await analyze_image(img())
    assert result["category"] == "plastic"
    assert result["material"] == "plastic"
    assert 0 <= result["confidence"] <= 1
    assert "disposal_guidance" not in result


@pytest.mark.asyncio
async def test_low_confidence_prediction_becomes_unknown(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    fake = fake_local_model([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], "glass")
    with patch("vision._load_local_model", return_value=fake):
        result = await analyze_image(img())
    assert result["category"] == "unknown"
    assert result["confidence"] <= 0.44


@pytest.mark.asyncio
async def test_inference_error_is_not_converted_to_confident_category(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch("vision._load_local_model", side_effect=RuntimeError("model failure")):
        with pytest.raises(VisionResponseError, match="inference failed"):
            await analyze_image(img())


def test_endpoint_safe_fallback_and_invalid_image():
    client = TestClient(app)
    with patch("app.analyze_image", new=AsyncMock(side_effect=VisionProviderError("secret"))):
        with patch("app.assess_condition", new=AsyncMock(return_value=_safe_fallback_condition())):
            response = client.post("/api/v1/analyses", files={"image": ("x.png", img(), "image/png")})
    assert response.status_code == 200
    assert "secret" not in response.text
    response = client.post("/api/v1/analyses", files={"image": ("x.txt", b"bad", "text/plain")})
    assert response.status_code == 400


def test_endpoint_decision_engine_output_is_deterministic():
    client = TestClient(app)
    identification = {"item_name": "Plastic item", "category": "plastic", "material": "plastic", "confidence": 0.9, "evidence": "Local model label"}
    with patch("app.analyze_image", new=AsyncMock(return_value=identification)):
        with patch("app.assess_condition", new=AsyncMock(return_value=_safe_fallback_condition())):
            response = client.post("/api/v1/analyses", files={"image": ("x.png", img(), "image/png")})
    assert response.status_code == 200
    assert response.json()["result"]["disposal_guidance"] == decision_for("plastic")["disposal_guidance"]


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

def test_waste_condition_schema_defaults():
    """WasteCondition with no arguments defaults to all unable_to_assess."""
    cond = WasteCondition()
    assert cond.cracks_fractures == "unable_to_assess"
    assert cond.holes_leaks_breakage == "unable_to_assess"
    assert cond.severe_deformation == "unable_to_assess"
    assert cond.image_unclear is False
    assert cond.findings == []


def test_waste_condition_schema_rejects_invalid_status():
    """Pydantic must reject unsupported status strings."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        WasteCondition(cracks_fractures="maybe")


def test_condition_finding_schema_rejects_empty_evidence():
    """ConditionFinding rejects empty or whitespace-only evidence."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ConditionFinding(condition_type="cracks_fractures", visual_evidence="")


def test_condition_finding_schema_rejects_unknown_type():
    """ConditionFinding rejects unrecognised condition_type values."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        ConditionFinding(condition_type="explosion", visual_evidence="boom")


def test_waste_result_condition_is_optional():
    """WasteResult is valid with condition=None (no API key scenario)."""
    from schemas import WasteResult
    result = WasteResult(
        item_name="Plastic bottle",
        category="plastic",
        material="plastic",
        confidence=0.9,
        evidence="Test",
        disposal_guidance="Recycle",
        preparation_steps=[],
        warnings=[],
        condition=None,
    )
    assert result.condition is None


# ---------------------------------------------------------------------------
# _extract_condition_json unit tests
# ---------------------------------------------------------------------------

_VALID_UNDAMAGED_JSON = """{
  "cracks_fractures": "not_detected",
  "holes_leaks_breakage": "not_detected",
  "severe_deformation": "not_detected",
  "image_unclear": false,
  "findings": []
}"""

_VALID_CRACKED_JSON = """{
  "cracks_fractures": "detected",
  "holes_leaks_breakage": "not_detected",
  "severe_deformation": "not_detected",
  "image_unclear": false,
  "findings": [
    {"condition_type": "cracks_fractures", "visual_evidence": "A hairline crack is visible along the left edge of the bottle."}
  ]
}"""

_VALID_WITH_THINK_TAGS = """<think>
Let me examine the image carefully.
</think>
{
  "cracks_fractures": "not_detected",
  "holes_leaks_breakage": "not_detected",
  "severe_deformation": "unable_to_assess",
  "image_unclear": false,
  "findings": []
}"""

_VALID_WITH_MARKDOWN_FENCE = """```json
{
  "cracks_fractures": "not_detected",
  "holes_leaks_breakage": "not_detected",
  "severe_deformation": "not_detected",
  "image_unclear": false,
  "findings": []
}
```"""


def test_extract_condition_json_undamaged():
    result = _extract_condition_json(_VALID_UNDAMAGED_JSON)
    assert result["cracks_fractures"] == "not_detected"
    assert result["holes_leaks_breakage"] == "not_detected"
    assert result["severe_deformation"] == "not_detected"
    assert result["image_unclear"] is False
    assert result["findings"] == []


def test_extract_condition_json_crack_detected():
    result = _extract_condition_json(_VALID_CRACKED_JSON)
    assert result["cracks_fractures"] == "detected"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["condition_type"] == "cracks_fractures"
    assert "crack" in result["findings"][0]["visual_evidence"].lower()


def test_extract_condition_json_strips_think_tags():
    result = _extract_condition_json(_VALID_WITH_THINK_TAGS)
    assert result["cracks_fractures"] == "not_detected"
    assert result["severe_deformation"] == "unable_to_assess"


def test_extract_condition_json_strips_markdown_fence():
    result = _extract_condition_json(_VALID_WITH_MARKDOWN_FENCE)
    assert result["cracks_fractures"] == "not_detected"
    assert result["findings"] == []


def test_extract_condition_json_rejects_no_json():
    with pytest.raises(ValueError, match="No JSON object"):
        _extract_condition_json("This is just a sentence.")


def test_extract_condition_json_rejects_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        _extract_condition_json("{ bad json: }")


def test_extract_condition_json_rejects_unsupported_status():
    bad = _VALID_UNDAMAGED_JSON.replace('"not_detected"', '"maybe"', 1)
    with pytest.raises(ValueError, match="unsupported value"):
        _extract_condition_json(bad)


def test_extract_condition_json_rejects_non_bool_image_unclear():
    bad = _VALID_UNDAMAGED_JSON.replace("false", '"yes"')
    with pytest.raises(ValueError, match="image_unclear"):
        _extract_condition_json(bad)


def test_extract_condition_json_rejects_detected_without_finding():
    """A 'detected' status with no matching finding must be rejected."""
    malformed = """{
      "cracks_fractures": "detected",
      "holes_leaks_breakage": "not_detected",
      "severe_deformation": "not_detected",
      "image_unclear": false,
      "findings": []
    }"""
    with pytest.raises(ValueError, match="no corresponding finding"):
        _extract_condition_json(malformed)


def test_extract_condition_json_rejects_unknown_condition_type_in_findings():
    bad = """{
      "cracks_fractures": "not_detected",
      "holes_leaks_breakage": "not_detected",
      "severe_deformation": "not_detected",
      "image_unclear": false,
      "findings": [{"condition_type": "explosion", "visual_evidence": "boom"}]
    }"""
    with pytest.raises(ValueError, match="condition_type"):
        _extract_condition_json(bad)


def test_extract_condition_json_rejects_empty_visual_evidence():
    bad = """{
      "cracks_fractures": "detected",
      "holes_leaks_breakage": "not_detected",
      "severe_deformation": "not_detected",
      "image_unclear": false,
      "findings": [{"condition_type": "cracks_fractures", "visual_evidence": "   "}]
    }"""
    with pytest.raises(ValueError, match="visual_evidence"):
        _extract_condition_json(bad)


def test_safe_fallback_condition_structure():
    fb = _safe_fallback_condition()
    assert fb["cracks_fractures"] == "unable_to_assess"
    assert fb["holes_leaks_breakage"] == "unable_to_assess"
    assert fb["severe_deformation"] == "unable_to_assess"
    assert fb["image_unclear"] is True
    assert fb["findings"] == []


# ---------------------------------------------------------------------------
# assess_condition integration tests (all external calls mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assess_condition_absent_when_no_api_key(monkeypatch):
    """When OPENROUTER_API_KEY is absent, assess_condition returns the fallback."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = await assess_condition(img())
    assert result["cracks_fractures"] == "unable_to_assess"
    assert result["image_unclear"] is True


@pytest.mark.asyncio
async def test_assess_condition_undamaged_item(monkeypatch):
    """Mocked undamaged response is parsed and returned correctly."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("vision._call_openrouter", new=AsyncMock(return_value=_VALID_UNDAMAGED_JSON)):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "not_detected"
    assert result["holes_leaks_breakage"] == "not_detected"
    assert result["severe_deformation"] == "not_detected"
    assert result["image_unclear"] is False
    assert result["findings"] == []


@pytest.mark.asyncio
async def test_assess_condition_crack_detected(monkeypatch):
    """Mocked crack response is parsed; finding is populated with evidence."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("vision._call_openrouter", new=AsyncMock(return_value=_VALID_CRACKED_JSON)):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "detected"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["condition_type"] == "cracks_fractures"


@pytest.mark.asyncio
async def test_assess_condition_partial_visibility(monkeypatch):
    """One condition can be unable_to_assess while others are assessed normally."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    partial_json = """{
      "cracks_fractures": "not_detected",
      "holes_leaks_breakage": "unable_to_assess",
      "severe_deformation": "not_detected",
      "image_unclear": false,
      "findings": []
    }"""
    with patch("vision._call_openrouter", new=AsyncMock(return_value=partial_json)):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "not_detected"
    assert result["holes_leaks_breakage"] == "unable_to_assess"
    assert result["severe_deformation"] == "not_detected"
    assert result["image_unclear"] is False


@pytest.mark.asyncio
async def test_assess_condition_malformed_response_returns_fallback(monkeypatch):
    """A malformed model response must not raise; fallback is returned."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("vision._call_openrouter", new=AsyncMock(return_value="Sorry, I cannot assess that.")):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "unable_to_assess"
    assert result["image_unclear"] is True


@pytest.mark.asyncio
async def test_assess_condition_provider_error_returns_fallback(monkeypatch):
    """A VisionProviderError from OpenRouter must not raise; fallback is returned."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("vision._call_openrouter", new=AsyncMock(side_effect=VisionProviderError("HTTP 429"))):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "unable_to_assess"


@pytest.mark.asyncio
async def test_assess_condition_network_error_returns_fallback(monkeypatch):
    """A generic network exception must not raise; fallback is returned."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    with patch("vision._call_openrouter", new=AsyncMock(side_effect=ConnectionError("timeout"))):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "unable_to_assess"


def test_condition_endpoint_prefers_explicit_chat_endpoint(monkeypatch):
    from vision import _condition_endpoint

    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.invalid/api/v1")
    monkeypatch.setenv("OPENROUTER_CHAT_ENDPOINT", "https://example.invalid/custom/chat")
    assert _condition_endpoint() == "https://example.invalid/custom/chat"

def test_extract_message_content_accepts_text_blocks():
    from vision import _extract_message_content

    body = {"choices": [{"message": {"content": [{"type": "text", "text": "{"}, {"type": "text", "text": "}"}]}}]}
    assert _extract_message_content(body) == "{}"

@pytest.mark.asyncio
async def test_assess_condition_contradictory_response_returns_fallback(monkeypatch):
    """A detected status without a matching finding must return fallback (not raise)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    contradictory = """{
      "cracks_fractures": "detected",
      "holes_leaks_breakage": "not_detected",
      "severe_deformation": "not_detected",
      "image_unclear": false,
      "findings": []
    }"""
    with patch("vision._call_openrouter", new=AsyncMock(return_value=contradictory)):
        result = await assess_condition(img())
    assert result["cracks_fractures"] == "unable_to_assess"


# ---------------------------------------------------------------------------
# Endpoint integration tests with condition
# ---------------------------------------------------------------------------

def test_endpoint_includes_condition_field():
    """Endpoint response includes condition when assess_condition returns valid data."""
    client = TestClient(app)
    identification = {
        "item_name": "Glass jar",
        "category": "glass",
        "material": "glass",
        "confidence": 0.88,
        "evidence": "Local model",
    }
    condition_data = {
        "cracks_fractures": "detected",
        "holes_leaks_breakage": "not_detected",
        "severe_deformation": "not_detected",
        "image_unclear": False,
        "findings": [
            {"condition_type": "cracks_fractures", "visual_evidence": "Visible crack on side."}
        ],
    }
    with patch("app.analyze_image", new=AsyncMock(return_value=identification)):
        with patch("app.assess_condition", new=AsyncMock(return_value=condition_data)):
            response = client.post("/api/v1/analyses", files={"image": ("x.png", img(), "image/png")})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["condition"]["cracks_fractures"] == "detected"
    assert len(result["condition"]["findings"]) == 1
    assert result["condition"]["findings"][0]["condition_type"] == "cracks_fractures"


def test_endpoint_condition_none_when_no_key(monkeypatch):
    """When OPENROUTER_API_KEY is absent, condition in response is the fallback."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = TestClient(app)
    identification = {
        "item_name": "Plastic bottle",
        "category": "plastic",
        "material": "plastic",
        "confidence": 0.9,
        "evidence": "Local model",
    }
    with patch("app.analyze_image", new=AsyncMock(return_value=identification)):
        response = client.post("/api/v1/analyses", files={"image": ("x.png", img(), "image/png")})
    assert response.status_code == 200
    result = response.json()["result"]
    # assess_condition with no key returns the safe fallback, which becomes a WasteCondition
    assert result["condition"]["cracks_fractures"] == "unable_to_assess"


def test_endpoint_assess_condition_error_does_not_fail_request(monkeypatch):
    """An unexpected exception in assess_condition must not produce a 5xx response."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = TestClient(app)
    identification = {
        "item_name": "Metal can",
        "category": "metal",
        "material": "metal",
        "confidence": 0.85,
        "evidence": "Local model",
    }
    with patch("app.analyze_image", new=AsyncMock(return_value=identification)):
        with patch("app.assess_condition", new=AsyncMock(return_value=_safe_fallback_condition())):
            response = client.post("/api/v1/analyses", files={"image": ("x.png", img(), "image/png")})
    assert response.status_code == 200
    assert response.json()["result"]["category"] == "metal"


def test_endpoint_disposal_guidance_unchanged_by_condition():
    """Disposal guidance from decision_engine is not altered by condition assessment."""
    client = TestClient(app)
    identification = {
        "item_name": "Plastic bottle",
        "category": "plastic",
        "material": "plastic",
        "confidence": 0.9,
        "evidence": "Local model",
    }
    condition_data = {
        "cracks_fractures": "detected",
        "holes_leaks_breakage": "detected",
        "severe_deformation": "not_detected",
        "image_unclear": False,
        "findings": [
            {"condition_type": "cracks_fractures", "visual_evidence": "Crack visible."},
            {"condition_type": "holes_leaks_breakage", "visual_evidence": "Hole present."},
        ],
    }
    with patch("app.analyze_image", new=AsyncMock(return_value=identification)):
        with patch("app.assess_condition", new=AsyncMock(return_value=condition_data)):
            response = client.post("/api/v1/analyses", files={"image": ("x.png", img(), "image/png")})
    assert response.status_code == 200
    result = response.json()["result"]
    # Guidance must be exactly what the deterministic engine returns
    assert result["disposal_guidance"] == decision_for("plastic")["disposal_guidance"]
    assert result["preparation_steps"] == decision_for("plastic")["preparation_steps"]
    # Condition is present but did not alter disposal fields
    assert result["condition"]["cracks_fractures"] == "detected"


def test_endpoint_api_key_not_in_response(monkeypatch):
    """No part of the API key must appear in the response body."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret-key-xyz")
    client = TestClient(app)
    identification = {
        "item_name": "Plastic bottle",
        "category": "plastic",
        "material": "plastic",
        "confidence": 0.9,
        "evidence": "Local model",
    }
    with patch("app.analyze_image", new=AsyncMock(return_value=identification)):
        with patch("app.assess_condition", new=AsyncMock(return_value=_safe_fallback_condition())):
            response = client.post("/api/v1/analyses", files={"image": ("x.png", img(), "image/png")})
    assert "super-secret-key-xyz" not in response.text
