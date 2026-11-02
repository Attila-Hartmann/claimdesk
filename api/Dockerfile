# One image, two Lambda functions (API and worker), selected by the function's command. Linux/amd64.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1
WORKDIR /app/api
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --group lambda --no-install-project
COPY api/claimdesk ./claimdesk
RUN uv sync --frozen --no-dev --group lambda

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-hun \
 && rm -rf /var/lib/apt/lists/*
ENV PATH=/app/api/.venv/bin:$PATH PYTHONUNBUFFERED=1 TESSERACT_CMD=tesseract
COPY --from=build /app /app
WORKDIR /app/api
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["claimdesk.handlers.api"]
