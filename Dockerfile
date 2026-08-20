# Personal Child Context Agent — Cloud Run backend (SOT-2794).
# Follows the おたよりナビ (toddler-private-rag) backend: python:3.11-slim + uvicorn,
# serving `pcca.api.app:app` on port 8080. Gemini is reached via Vertex AI and
# Firestore via ADC, so no API keys are baked into the image.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

# Install the package with its serving extras. Copy metadata + sources first so the
# build has everything setuptools needs to resolve the src-layout package.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[serving]"

EXPOSE 8080

# Bind to the Cloud Run-provided $PORT (defaults to 8080 locally).
CMD ["sh", "-c", "uvicorn pcca.api.app:app --host 0.0.0.0 --port ${PORT}"]
