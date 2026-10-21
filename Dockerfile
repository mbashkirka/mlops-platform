# syntax=docker/dockerfile:1

FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app \
    && mkdir -p /var/lib/mlflow /var/lib/mlops/events /app/data/raw /app/data/monitoring /app/artifacts \
    && chown -R app:app /var/lib/mlflow /var/lib/mlops /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[serve]"

COPY configs ./configs
COPY scripts ./scripts
RUN chmod +x scripts/compose_bootstrap.sh \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2).read()"]

CMD ["uvicorn", "mlops_platform.api:app", "--host", "0.0.0.0", "--port", "8000"]
