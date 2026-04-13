"""
routers/chat.py — Endpoint conversacional principal do Nicodemus ADM.

POST /chat/
  1. Valida JWT → CurrentUser (inclui .name)
  2. Carrega/retoma sessão (get_or_resume)
  3. Carrega contexto Redis (get_context)
  4. Monta NicoState com a mensagem atual
  5. Invoca nico_graph (ReAct loop)
  6. Persiste user_message + assistant_reply no banco
  7. Atualiza contexto Redis (append_turn)
  8. Auto-gera título na primeira mensagem (se ainda "Nova conversa")
  9. Detecta file_id gerado por tool e monta file_url
  10. Retorna ChatResponse
"""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from agent.nico_agent import nico_graph
from agent.state import NicoState
from core import memory
from core.auth import CurrentUser, get_current_user
from core.database import get_session
from core.settings import settings
from schemas.session_types import ChatRequest, ChatResponse
from services.session_service import SessionService

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession  = Depends(get_session),
):
    """
    Processa mensagem do gestor e retorna resposta do Nicodemus.
    Mantém contexto conversacional via Redis (curto prazo) e PostgreSQL (persistência).
    """
    # 1 — Carrega/retoma sessão
    try:
        session = await SessionService.get_or_resume(db, body.session_id, user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if session.status == "completed":
        raise HTTPException(
            status_code=400,
            detail="Sessão encerrada. Crie uma nova sessão para continuar.",
        )

    # 2 — Contexto Redis + mensagem atual
    context     = await memory.get_context(body.session_id)
    user_msg    = {"role": "user", "content": body.message}
    context_now = context + [user_msg]

    # 3 — Monta estado inicial do agente
    initial_state: NicoState = {
        "user_id":      user.user_id,
        "school_id":    session.school_id,
        "sa_token":     user.sa_token,
        "role":         user.role,
        "user_name":    user.name,
        "session_id":   body.session_id,
        "messages":     context_now,
        "user_message": body.message,
        "tool_calls":   [],
        "response":     "",
        "error":        None,
    }

    logger.info(
        "chat.invoke",
        session_id=body.session_id,
        user_id=user.user_id,
        msg_len=len(body.message),
    )

    # 4 — Executa o agente ReAct
    final_state: NicoState = await nico_graph.ainvoke(initial_state)

    if final_state.get("error"):
        logger.error("chat.agent_error", error=final_state["error"])
        raise HTTPException(status_code=500, detail=final_state["error"])

    reply = final_state.get("response", "")

    # 5 — Persiste mensagens no banco
    await SessionService.add_message(db, session, "user",      body.message)
    await SessionService.add_message(db, session, "assistant", reply)

    # 6 — Atualiza contexto Redis
    assistant_msg = {"role": "assistant", "content": reply}
    await memory.append_turn(body.session_id, user_msg, assistant_msg)

    # 7 — Auto-gera título na primeira mensagem
    if session.title == "Nova conversa" and session.message_count <= 2:
        title = await _auto_title(body.message)
        await SessionService.set_title(db, session, title)

    # 8 — Detecta arquivo gerado por tool
    file_id  = _extract_file_id(final_state)
    file_url = f"/report/download/{file_id}" if file_id else None

    if file_id:
        await SessionService.increment_report_count(db, session)

    logger.info("chat.ok", session_id=body.session_id, has_file=bool(file_id))

    return ChatResponse(
        session_id=body.session_id,
        reply=reply,
        file_id=file_id,
        file_url=file_url,
    )


async def _auto_title(first_message: str) -> str:
    """Gera título curto (máx 60 chars) baseado na primeira mensagem do gestor."""
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        api_key=settings.openai_api_key,
        temperature=0,
    )
    response = await llm.ainvoke([
        SystemMessage(
            content="Gere um título curto (máximo 60 caracteres) para uma conversa de gestão "
                    "escolar que começa com a mensagem abaixo. Responda apenas o título, sem aspas."
        ),
        HumanMessage(content=first_message[:300]),
    ])
    return response.content.strip()[:500]


def _extract_file_id(state: NicoState) -> str | None:
    """
    Varre as mensagens de tool do estado (ordem reversa) em busca de file_id gerado.
    Retorna o primeiro encontrado ou None.
    """
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "tool":
            try:
                result = json.loads(msg.get("content", "{}"))
                if "file_id" in result:
                    return result["file_id"]
            except (json.JSONDecodeError, AttributeError):
                continue
    return None
