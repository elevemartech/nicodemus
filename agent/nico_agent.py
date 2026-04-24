"""
agent/nico_agent.py — Agente conversacional ReAct para gestores escolares.

StateGraph: llm_node → should_use_tools → tool_node → llm_node (loop) | END

O LLM decide quando usar ferramentas (ReAct pattern).
O tool_node injeta sa_token e school_id em cada chamada de ferramenta.
As mensagens ficam em list[dict] (formato OpenAI) para serializar direto no Redis.
"""
from __future__ import annotations

import json

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from agent.state import NicoState
from agent.tools import TOOLS_REGISTRY
from core.settings import settings

logger = structlog.get_logger(__name__)

_llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=settings.openai_api_key,
    temperature=0,
).bind_tools(TOOLS_REGISTRY)


def _build_system_prompt(user_name: str, role: str) -> str:
    return (
        f"Você é o Nicodemus ADM, copiloto de gestão escolar da plataforma Eleve.\n"
        f"Você está atendendo {user_name} ({role}).\n\n"
        "Você pode ajudar com:\n"
        "- Relatórios de inadimplência, matrículas e solicitações\n"
        "- Perguntas sobre gestão escolar em linguagem natural\n"
        "- Interpretação de dados e indicadores da escola\n"
        "- Gestão inteligente de FAQs da escola (analisar, organizar, criar, auditar)\n\n"
        "Para FAQs, use as ferramentas: analyze_faqs → build_faq_plan → (aguardar aprovação) → execute_faq_plan\n"
        "NUNCA execute_faq_plan sem confirmação explícita do gestor.\n\n"
        "Regras:\n"
        f"- Seja objetivo e profissional. Chame o gestor pelo nome ({user_name}).\n"
        "- Quando gerar um relatório, confirme o file_id retornado pela ferramenta.\n"
        "- Nunca invente dados — use apenas o que as ferramentas retornam.\n"
        "- Se não souber responder, diga claramente.\n"
        "- Responda sempre em português brasileiro.\n"
        "- Para FAQs: sempre mostre o plano ANTES de executar. Nunca execute sem aprovação.\n"
    )


async def llm_node(state: NicoState) -> NicoState:
    """
    Chama gpt-4o-mini com as mensagens da sessão.
    Converte list[dict] → objetos LangChain para a chamada, e retorna de volta a dict.
    """
    user_name = state.get("user_name", "Gestor")
    role      = state.get("role", "manager")
    messages  = state.get("messages", [])

    # Converte dicts → LangChain messages
    lc_messages: list = [SystemMessage(content=_build_system_prompt(user_name, role))]
    for m in messages:
        r = m.get("role")
        c = m.get("content", "")
        if r == "user":
            lc_messages.append(HumanMessage(content=c))
        elif r == "assistant":
            lc_messages.append(AIMessage(content=c))
        elif r == "tool":
            lc_messages.append(
                ToolMessage(content=c, tool_call_id=m.get("tool_call_id", ""))
            )

    # Detecta intenção FAQ a partir da última mensagem do utilizador
    faq_keywords = {
        "analyze": ["analise", "diagnóstico", "diagnose", "analis"],
        "audit": ["duplicada", "duplicado", "vazia", "vazio", "sem resposta", "auditoria", "audit"],
        "organize": ["organiz", "categori", "agrupe", "reorganiz"],
        "create": ["crie", "cria", "nova faq", "adicione", "adiciona"],
        "edit": ["melhore", "melhora", "corrija", "corrige", "actualize", "atualize"],
        "bulk_clean": ["corrija todos", "limpe todas", "bulk", "em massa"],
    }
    last_user_msg = next(
        (m["content"].lower() for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    faq_intent = None
    if any(kw in last_user_msg for kws in faq_keywords.values() for kw in kws):
        if any(trigger in last_user_msg for trigger in ("faq", "pergunta", "base de conhecimento")):
            for intent, keywords in faq_keywords.items():
                if any(kw in last_user_msg for kw in keywords):
                    faq_intent = intent
                    break

    logger.info(
        "nico_agent.llm_call",
        session_id=state.get("session_id"),
        msg_count=len(lc_messages),
    )

    response = await _llm.ainvoke(lc_messages)

    # Extrai tool_calls se houver
    tool_calls = []
    if response.tool_calls:
        tool_calls = [
            {
                "id":        tc["id"],
                "name":      tc["name"],
                "arguments": tc["args"],
            }
            for tc in response.tool_calls
        ]

    # Append a resposta do assistente ao histórico
    new_messages = list(messages) + [{"role": "assistant", "content": response.content or ""}]

    return {
        **state,
        "messages":   new_messages,
        "tool_calls": tool_calls,
        "response":   response.content or "",
        "error":      None,
        **({"faq_intent": faq_intent} if faq_intent else {}),
    }


async def tool_node(state: NicoState) -> NicoState:
    """
    Executa os tool_calls do turno atual.
    Injeta sa_token e school_id em cada chamada e adiciona os resultados ao histórico.
    """
    tool_calls = state.get("tool_calls", [])
    sa_token   = state.get("sa_token", "")
    school_id  = state.get("school_id", "")
    messages   = list(state.get("messages", []))

    tool_map = {t.name: t for t in TOOLS_REGISTRY}

    for tc in tool_calls:
        name    = tc["name"]
        args    = dict(tc.get("arguments", {}))
        tc_id   = tc.get("id", "")
        tool_fn = tool_map.get(name)

        if not tool_fn:
            result_str = json.dumps({"error": f"Ferramenta '{name}' não encontrada."})
        else:
            # Injeta contexto de autenticação
            args["sa_token"]  = sa_token
            args["school_id"] = school_id
            try:
                result_str = await tool_fn.ainvoke(args)
            except Exception as exc:
                logger.error("tool_node.error", tool=name, error=str(exc))
                result_str = json.dumps({"error": str(exc)})

        messages.append({
            "role":         "tool",
            "content":      result_str,
            "tool_call_id": tc_id,
            "tool_name":    name,
        })

        logger.info("tool_node.executed", tool=name, session_id=state.get("session_id"))

    return {**state, "messages": messages, "tool_calls": []}


def should_use_tools(state: NicoState) -> str:
    """Rota condicional: há tool_calls → tool_node; senão → END."""
    return "tool_node" if state.get("tool_calls") else END


def build_nico_graph() -> StateGraph:
    graph = StateGraph(NicoState)

    graph.add_node("llm_node",  llm_node)
    graph.add_node("tool_node", tool_node)

    graph.set_entry_point("llm_node")
    graph.add_conditional_edges(
        "llm_node",
        should_use_tools,
        {"tool_node": "tool_node", END: END},
    )
    graph.add_edge("tool_node", "llm_node")

    return graph.compile()


nico_graph = build_nico_graph()
