"""
agent/tools/get_school_summary.py — Ferramenta de resumo diário da escola.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from langchain_core.tools import tool

from core.api_client import DjangoAPIClient


@tool
async def get_school_summary(
    sa_token: str = "",
    school_id: str = "",
    user_name: str = "",
    **kwargs,
) -> str:
    """
    Retorna um resumo do estado atual da escola para briefing diário.
    Use quando o gestor perguntar 'como está a escola hoje?',
    'o que tenho para hoje?', 'qual o resumo do dia?' ou similar.
    """

    async def _fetch_open_requests() -> dict:
        async with DjangoAPIClient(token=sa_token) as client:
            return await client.get(
                "/api/v1/requests/",
                params={"status": "open", "page_size": 5},
            )

    async def _fetch_pending_enrollments() -> dict:
        async with DjangoAPIClient(token=sa_token) as client:
            return await client.get(
                "/api/v1/secretary/enrollments/",
                params={"status": "pending", "page_size": 5},
            )

    async def _fetch_inadimplencia() -> dict:
        async with DjangoAPIClient(token=sa_token) as client:
            return await client.get(
                "/api/v1/requests/",
                params={"request_type": "boleto_2via", "status": "open", "page_size": 1},
            )

    results = await asyncio.gather(
        _fetch_open_requests(),
        _fetch_pending_enrollments(),
        _fetch_inadimplencia(),
        return_exceptions=True,
    )

    req_result, enroll_result, inadimp_result = results

    solicitacoes_count = 0
    solicitacoes_exemplos: list[str] = []
    if not isinstance(req_result, Exception):
        solicitacoes_count = req_result.get("count", len(req_result.get("results", [])))
        solicitacoes_exemplos = [
            e.get("protocol", str(e.get("id", "")))
            for e in req_result.get("results", [])[:5]
        ]

    matriculas_count = 0
    matriculas_exemplos: list[str] = []
    if not isinstance(enroll_result, Exception):
        matriculas_count = enroll_result.get("count", len(enroll_result.get("results", [])))
        matriculas_exemplos = [
            e.get("student_name", e.get("nome", ""))
            for e in enroll_result.get("results", [])[:5]
        ]

    inadimplencia_count = 0
    if not isinstance(inadimp_result, Exception):
        inadimplencia_count = inadimp_result.get("count", 0)

    hoje = datetime.now().strftime("%d/%m/%Y")

    summary = {
        "summary_data": (
            f"RESUMO_ESCOLA:\n"
            f"solicitacoes_abertas: {solicitacoes_count} | exemplos: {solicitacoes_exemplos}\n"
            f"matriculas_pendentes: {matriculas_count} | exemplos: {matriculas_exemplos}\n"
            f"inadimplencia_aberta: {inadimplencia_count} registros\n"
            f"user_name: {user_name}\n"
            f"data_hoje: {hoje}"
        )
    }
    return json.dumps(summary)
