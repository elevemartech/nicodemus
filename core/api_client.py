"""
core/api_client.py — Cliente HTTP assíncrono para a Eleve API.

Mesmo padrão do eleve-agent. Usa ServiceKey do ServiceAccount da escola.
Sempre use como context manager para fechar a conexão corretamente.

Exemplo:
    async with DjangoAPIClient(token=user.sa_token) as client:
        result = await client.get("/api/v1/requests/")
"""
from __future__ import annotations

import httpx
import structlog
from core.settings import settings

logger = structlog.get_logger(__name__)


class DjangoAPIClient:
    def __init__(self, token: str, timeout: float = 20.0):
        self._token = token
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "DjangoAPIClient":
        self._client = httpx.AsyncClient(
            base_url=settings.eleve_api_url,
            headers={"Authorization": f"ServiceKey {self._token}"},
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    async def get(self, path: str, **kwargs) -> dict | list:
        resp = await self._client.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json: dict, **kwargs) -> dict:
        resp = await self._client.post(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def patch(self, path: str, json: dict, **kwargs) -> dict:
        resp = await self._client.patch(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()
