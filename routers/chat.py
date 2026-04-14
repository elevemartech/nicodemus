"""
routers/chat.py — Endpoint de chat conversacional do Nicodemus ADM.

Fluxo:
  POST /chat/message
    → classifica intenção (intent_node)
    → "relatorio"  → report_agent → retorna summary + download_url
    → "documento"  → orienta upload via /doc/extract
    → "geral"      → resposta conversacional via LLM
    → "outro"      → fallback amigável

O JWT do usuário logado no dashboard é obrigatório (mesmo padrão dos outros routers).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agents.report_agent import report_graph
from agents.state import NicoState
from core.auth import CurrentUser, get_current_user
from core.settings import settings
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

logger = structlog.get_logger(__name__)

router = APIRouter()

_llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=settings.openai_api_key,
    temperature=0.3,
)

# ── Schemas ───────────────────────────────────────────────────────────────────

class ChatMessageRequest(BaseModel):
    message: str
    context: dict | None = None  # { route: "/secretaria", page: "board" }

class ChatMessageResponse(BaseModel):
    reply: str
    intent: str
    download_url: str | None = None
    file_id: str | None = None
    report_preview: list[dict] | None = None

# ── Intent classifier ─────────────────────────────────────────────────────────

_INTENT_SYSTEM = """\
Você é um classificador de intenção para o Nicodemus ADM, copiloto de gestão escolar.

Classifique a mensagem do usuário em UMA das categorias abaixo.
Responda APENAS com a palavra da categoria, sem explicação:

- relatorio   → usuário quer gerar ou consultar um relatório, lista, planilha ou dado agregado
- documento   → usuário quer processar, ler, validar ou registrar um documento físico (comprovante, contrato, boletim)
- geral       → pergunta sobre o sistema, processo escolar, dúvida administrativa
- outro       → qualquer coisa fora do escopo acima
"""

async def classify_intent(message: str) -> str:
    try:
        resp = await _llm.ainvoke([
            SystemMessage(content=_INTENT_SYSTEM),
            HumanMessage(content=message),
        ])
        intent = resp.content.strip().lower()
        return intent if intent in {"relatorio", "documento", "geral", "outro"} else "outro"
    except Exception as exc:
        logger.warning("chat.intent_error", error=str(exc))
        return "geral"

# ── Intent handlers ───────────────────────────────────────────────────────────

async def handle_relatorio(message: str, user: CurrentUser) -> ChatMessageResponse:
    """Roteia para o report_agent e retorna link de download."""
    initial_state: NicoState = {
        "user_id":     user.user_id,
        "school_id":   user.school_id,
        "sa_token":    user.sa_token,
        "role":        user.role,
        "user_prompt": message,
        "file_format": "xlsx",
    }

    final_state: NicoState = await report_graph.ainvoke(initial_state)

    if final_state.get("error"):
        logger.error("chat.report_error", error=final_state["error"])
        return ChatMessageResponse(
            reply="Não consegui gerar o relatório agora. Tente novamente ou reformule o pedido.",
            intent="relatorio",
        )

    summary      = final_state.get("summary", "Relatório gerado.")
    file_id      = final_state.get("file_id", "")
    plan         = final_state.get("report_plan", {})
    preview      = final_state.get("report_data", [])[:5]
    download_url = f"/report/download/{file_id}" if file_id else None

    reply = f"{summary}"
    if download_url:
        reply += "\n\nRelatório pronto para download."
    if plan.get("title"):
        reply = f"**{plan['title']}**\n\n{reply}"

    return ChatMessageResponse(
        reply=reply,
        intent="relatorio",
        download_url=download_url,
        file_id=file_id,
        report_preview=preview if preview else None,
    )


async def handle_documento(message: str) -> ChatMessageResponse:
    """Orienta o usuário a usar o upload de documento."""
    return ChatMessageResponse(
        reply=(
            "Para processar um documento, use o botão **Enviar Documento** "
            "na aba de Secretaria. Suporto comprovantes de pagamento, "
            "contratos de matrícula e boletins.\n\n"
            "Após o upload, extraio os dados automaticamente e aguardo sua confirmação antes de registrar."
        ),
        intent="documento",
    )


async def handle_geral(message: str, user: CurrentUser) -> ChatMessageResponse:
    """Resposta conversacional via LLM com contexto escolar."""
    _GENERAL_SYSTEM = """\
Você é o Nicodemus ADM, copiloto de gestão escolar do painel Sophia (Eleve).
Responda de forma direta e útil para gestores escolares — diretores, secretaria e admin.
Seja conciso. Use linguagem profissional mas acessível.
Se não souber a resposta, diga claramente e sugira onde encontrar a informação.
Nunca invente dados ou números.
"""
    try:
        resp = await _llm.ainvoke([
            SystemMessage(content=_GENERAL_SYSTEM),
            HumanMessage(content=message),
        ])
        return ChatMessageResponse(reply=resp.content.strip(), intent="geral")
    except Exception as exc:
        logger.error("chat.geral_error", error=str(exc))
        return ChatMessageResponse(
            reply="Não consegui processar sua mensagem. Tente novamente.",
            intent="geral",
        )


async def handle_outro() -> ChatMessageResponse:
    return ChatMessageResponse(
        reply=(
            "Posso ajudar com relatórios, documentos e processos administrativos da escola. "
            "Tente algo como:\n\n"
            "• *\"Alunos inadimplentes de abril em Excel\"*\n"
            "• *\"Como faço uma matrícula?\"*\n"
            "• *\"Processar comprovante de pagamento\"*"
        ),
        intent="outro",
    )

# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/message", response_model=ChatMessageResponse)
async def chat_message(
    body: ChatMessageRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """
    Ponto de entrada do chat conversacional do Nicodemus ADM.

    Classifica a intenção e roteia para o handler correto.
    O JWT do dashboard Eleve é obrigatório — mesmo padrão dos outros routers.
    """
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="Mensagem não pode ser vazia.")

    logger.info(
        "chat.message",
        user_id=user.user_id,
        school_id=user.school_id,
        message_preview=body.message[:80],
    )

    intent = await classify_intent(body.message)

    logger.info("chat.intent", intent=intent, user_id=user.user_id)

    if intent == "relatorio":
        return await handle_relatorio(body.message, user)
    if intent == "documento":
        return await handle_documento(body.message)
    if intent == "geral":
        return await handle_geral(body.message, user)
    return await handle_outro()