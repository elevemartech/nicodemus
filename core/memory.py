"""
core/memory.py — Contexto conversacional em Redis.

Armazena as últimas N mensagens de cada sessão para acesso rápido pelo agente.
O banco de dados (PostgreSQL) é a fonte de verdade; o Redis é cache de trabalho.

Key:   nicodemus:context:{session_id}
Valor: JSON list de mensagens no formato OpenAI {"role": ..., "content": ...}
TTL:   24 horas (sessões inativas expiram automaticamente)
Limite: MAX_TURNS mensagens (trunca as mais antigas)
"""
from __future__ import annotations

import json

from redis.asyncio import Redis

from core.settings import settings

MAX_TURNS = 20
_KEY_PREFIX = "nicodemus:context"
_TTL_SECONDS = 86_400  # 24 horas


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}:{session_id}"


def _get_redis() -> Redis:
    """Cria novo cliente Redis por chamada — evita problemas de event loop em workers."""
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def get_context(session_id: str) -> list[dict]:
    """Retorna a lista de mensagens da sessão. Retorna [] se não existir."""
    r = _get_redis()
    try:
        raw = await r.get(_key(session_id))
        return json.loads(raw) if raw else []
    finally:
        await r.aclose()


async def set_context(session_id: str, messages: list[dict]) -> None:
    """Persiste a lista de mensagens, truncando em MAX_TURNS e renovando TTL."""
    r = _get_redis()
    try:
        truncated = messages[-MAX_TURNS:]
        await r.set(_key(session_id), json.dumps(truncated), ex=_TTL_SECONDS)
    finally:
        await r.aclose()


async def append_turn(
    session_id: str,
    user_msg: dict,
    assistant_msg: dict,
) -> None:
    """Adiciona um par user/assistant ao contexto e trunca se necessário."""
    current = await get_context(session_id)
    current.extend([user_msg, assistant_msg])
    await set_context(session_id, current)


async def rebuild_from_db(session_id: str, messages: list[dict]) -> None:
    """
    Repopula o contexto Redis a partir de mensagens lidas do banco.
    Usado ao retomar sessões pausadas cujo contexto Redis expirou.
    """
    await set_context(session_id, messages)


async def clear_context(session_id: str) -> None:
    """Remove o contexto Redis ao encerrar uma sessão."""
    r = _get_redis()
    try:
        await r.delete(_key(session_id))
    finally:
        await r.aclose()
