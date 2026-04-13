"""
routers/report.py — Endpoints de geração e download de relatórios.

POST /report/generate      → interpreta pedido, busca dados, gera arquivo
GET  /report/download/{id} → serve o arquivo gerado (TTL: 15 min)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from agents.report_agent import report_graph
from agents.state import NicoState
from core.auth import CurrentUser, get_current_user
from core.file_storage import get_file
from schemas.report_types import SUPPORTED_FORMATS

logger = structlog.get_logger(__name__)

router = APIRouter()

MIME_MAP = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ReportRequest(BaseModel):
    prompt: str
    format: str = "xlsx"


# ── POST /report/generate ──────────────────────────────────────────────────────

@router.post("/generate")
async def generate_report_endpoint(
    body: ReportRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Gera um relatório a partir de um pedido em linguagem natural.

    O Nicodemus interpreta o pedido, consulta a eleve-api e entrega
    o arquivo no formato solicitado (.xlsx ou .docx).

    Args:
        prompt: Pedido em linguagem natural.
                Ex: "Alunos inadimplentes de abril em Excel"
        format: Formato do arquivo — "xlsx" (padrão) ou "docx".

    Returns:
        file_id para download via GET /report/download/{file_id},
        summary textual e preview dos primeiros registros.
    """
    fmt = body.format.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Formato inválido. Use: {', '.join(SUPPORTED_FORMATS)}",
        )

    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt não pode ser vazio.")

    logger.info(
        "report.generate.start",
        user_id=user.user_id,
        school_id=user.school_id,
        format=fmt,
        prompt=body.prompt[:80],
    )

    initial_state: NicoState = {
        "user_id":     user.user_id,
        "school_id":   user.school_id,
        "sa_token":    user.sa_token,
        "role":        user.role,
        "user_prompt": body.prompt,
        "file_format": fmt,
    }

    final_state: NicoState = await report_graph.ainvoke(initial_state)

    if final_state.get("error"):
        logger.error("report.generate.error", error=final_state["error"])
        raise HTTPException(status_code=500, detail=final_state["error"])

    file_id    = final_state.get("file_id", "")
    summary    = final_state.get("summary", "")
    data       = final_state.get("report_data", [])
    plan       = final_state.get("report_plan", {})

    logger.info(
        "report.generate.ok",
        file_id=file_id,
        rows=len(data),
        entity=plan.get("entity"),
    )

    return {
        "file_id":      file_id,
        "download_url": f"/report/download/{file_id}",
        "format":       fmt,
        "summary":      summary,
        "total":        len(data),
        "preview":      data[:5],          # primeiros 5 registros para preview no dashboard
        "plan":         plan,
    }


# ── GET /report/download/{file_id} ────────────────────────────────────────────

@router.get("/download/{file_id}")
async def download_report_endpoint(
    file_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Serve o arquivo gerado para download.

    O arquivo expira em 15 minutos após a geração.
    Após expirar, gere um novo relatório.
    """
    result = get_file(file_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado ou expirado. Gere o relatório novamente.",
        )

    file_bytes, extension = result
    mime = MIME_MAP.get(extension, "application/octet-stream")

    logger.info("report.download", file_id=file_id, user_id=user.user_id, ext=extension)

    return Response(
        content=file_bytes,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="relatorio_nicodemus.{extension}"',
            "Cache-Control": "no-store",
        },
    )
