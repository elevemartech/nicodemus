# ===================================================================
# Nicodemus ADM — Dockerfile (Produção)
# FastAPI + LangGraph + SQLAlchemy async | Python 3.12 | Poetry
# Multi-stage build — imagem final mínima
# ===================================================================

# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Instalar dependências de sistema necessárias para compilar
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar Poetry
ENV POETRY_HOME=/opt/poetry \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

# Copiar apenas os manifestos primeiro (aproveita cache de layers)
COPY pyproject.toml poetry.lock* ./

# Instalar apenas dependências de produção
RUN poetry install --no-root --only=main

# Copiar código
COPY . .


# ── Stage 2: Production ──────────────────────────────────────────
FROM python:3.12-slim AS production

# Runtime deps apenas
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Criar usuário não-root (segurança)
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copiar venv e código do builder
COPY --from=builder --chown=appuser:appgroup /app /app

# Ativar venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Trocar para usuário não-root
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
    CMD curl -f http://localhost:8001/health || exit 1

EXPOSE 8001

# Entrypoint: migrate + start
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8001 --workers 2 --log-level info --access-log"]