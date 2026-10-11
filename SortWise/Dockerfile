FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface \
    TRANSFORMERS_CACHE=/opt/huggingface/transformers

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Preload the exact checkpoint used by vision.py. Runtime loading remains
# local-only, so the API never downloads model files during a request.
RUN python -c "from transformers import AutoImageProcessor, SiglipForImageClassification; model='prithivMLmods/Trash-Net'; AutoImageProcessor.from_pretrained(model); SiglipForImageClassification.from_pretrained(model)"

COPY . ./

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
