"""
Nicodemus ADM — entry point FastAPI.

Copiloto de gestão escolar: leitura de documentos e geração de relatórios.
Serve exclusivamente gestores autenticados via JWT do dashboard Eleve.

Endpoints:
  POST /doc/extract         → extrai dados de documento via GPT-4o Vision
  POST /doc/confirm         → confirma extração e persiste na eleve-api
  POST /report/generate     → gera relatório .xlsx ou .docx
  GET  /report/download/{id}→ serve o arquivo gerado
  GET  /health              → healthcheck
"""
from __future__ import annotations

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.settings import settings
from routers.doc import router as doc_router
from routers.report import router as report_router
from routers.sessions import router as sessions_router
from routers.chat import router as chat_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("nicodemus_adm.startup", env=settings.environment)
    yield
    logger.info("nicodemus_adm.shutdown")


app = FastAPI(
    title="Nicodemus ADM",
    version="1.0.0",
    description="Copiloto de gestão escolar — Eleve",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(doc_router,      prefix="/doc",      tags=["Documentos"])
app.include_router(report_router,   prefix="/report",   tags=["Relatórios"])
app.include_router(sessions_router, prefix="/sessions", tags=["Sessões"])
app.include_router(chat_router,     prefix="/chat",     tags=["Chat"])


@app.get("/health", tags=["Infra"])
async def health():
    return {"status": "ok", "service": "nicodemus-adm"}
