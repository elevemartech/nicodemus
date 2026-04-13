"""
core/auth.py — Validação de JWT do dashboard Eleve.

O Nicodemus ADM só aceita requisições de gestores autenticados.
O token JWT é emitido pelo Django quando o usuário faz login no dashboard.

Roles permitidas: director | secretary | admin

Fluxo:
  Authorization: Bearer <jwt>
    → decodifica payload
    → valida role
    → retorna CurrentUser com sa_token para chamar eleve-api
"""
from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from core.settings import settings

logger = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

ALLOWED_ROLES = {"director", "secretary", "admin", "manager"}


class CurrentUser(BaseModel):
    user_id:   str
    school_id: str
    role:      str
    sa_token:  str      # ServiceKey para chamar a eleve-api
    name:      str      # nome do gestor (para personalização)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """
    Dependency FastAPI — injeta usuário autenticado em todos os endpoints.

    Espera payload JWT com:
      user_id   → UUID do usuário no Django
      school_id → ID da escola (isolamento multi-tenant)
      role      → "director" | "secretary" | "admin"
      sa_token  → ServiceKey da escola para a eleve-api

    Raises:
      401 → token inválido, expirado ou ausente
      403 → role não autorizada para o Nicodemus ADM
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str | None   = payload.get("user_id")
        school_id: str | None = payload.get("school_id")
        role: str | None      = payload.get("role")
        sa_token: str | None  = payload.get("sa_token")
        name: str             = payload.get("name") or payload.get("user_id") or "Gestor"

        if not all([user_id, school_id, role, sa_token]):
            raise credentials_exc

    except JWTError as exc:
        logger.warning("auth.jwt_error", error=str(exc))
        raise credentials_exc

    if role not in ALLOWED_ROLES:
        logger.warning("auth.role_denied", user_id=user_id, role=role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role}' não tem acesso ao Nicodemus ADM.",
        )

    logger.info("auth.ok", user_id=user_id, school_id=school_id, role=role)
    return CurrentUser(
        user_id=user_id,
        school_id=school_id,
        role=role,
        sa_token=sa_token,
        name=name,
    )
