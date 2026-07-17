FROM ghcr.io/astral-sh/uv:0.7.13 AS uv
FROM python:3.12.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
COPY --from=uv /uv /uvx /bin/
WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY services/ml/pyproject.toml services/ml/pyproject.toml
RUN uv sync --frozen --no-dev --package ufc-predictor-ml --no-install-project

COPY services/ml services/ml
RUN uv sync --frozen --no-dev --package ufc-predictor-ml

USER app
ENTRYPOINT ["uv", "run", "--no-sync", "ufc-predictor"]
CMD ["info"]
