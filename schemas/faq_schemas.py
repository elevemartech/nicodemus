from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FaqItem(BaseModel):
    """Representa uma FAQ existente vinda da eleve-api."""

    id: int
    question: str
    answer: str
    category: str
    status: Literal["active", "inactive"] = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FaqDiff(BaseModel):
    """Before/after de uma acção proposta."""

    question: str | None = None
    answer: str | None = None
    category: str | None = None
    status: str | None = None


class FaqAction(BaseModel):
    """Unidade atómica do plano — uma acção sobre uma FAQ."""

    id: str = Field(..., description="ID único da acção no plano, ex: act_1")
    type: Literal["create", "edit", "deactivate"]
    faq_id: int | None = None        # None para creates
    before: FaqDiff | None = None    # None para creates
    after: FaqDiff
    reason: str                      # justificativa em PT-BR gerada pelo LLM
    approved: bool = True            # gestor pode mudar para False
    status: Literal["pending", "done", "failed", "skipped"] = "pending"


class FaqPlan(BaseModel):
    """Plano completo gerado pelo Nicodemus — aguarda aprovação do gestor."""

    plan_id: str
    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    intent: str                      # "analyze"|"organize"|"audit"|"create"|"edit"|"bulk_clean"
    summary: dict[str, int]          # ex: {"edit": 4, "create": 2, "deactivate": 1}
    actions: list[FaqAction]
    analysis_text: str               # texto em PT-BR com o resumo da análise


class FaqIssue(BaseModel):
    """Problema encontrado pelo FaqAnalyzer numa FAQ existente."""

    faq_id: int
    question: str
    issue_type: Literal["empty_answer", "duplicate", "wrong_category", "stale", "quality"]
    description: str
    severity: Literal["error", "warning", "info"] = "warning"


class FaqAnalysisResult(BaseModel):
    """Resultado da análise determinística do FaqAnalyzer."""

    total_faqs: int
    issues: list[FaqIssue]
    coverage_gaps: list[str]               # categorias sem FAQs
    duplicate_groups: list[list[int]]      # grupos de IDs de FAQs duplicadas
    stale_count: int
    empty_count: int
    quality_count: int


# ── Schemas de request/response da API ───────────────────────────────────────


class FaqExecuteRequest(BaseModel):
    """Body do POST /chat/faq/execute."""

    session_id: str
    plan_id: str
    actions: list[dict]              # lista de {id, approved, after?}


class FaqExecuteActionResult(BaseModel):
    """Resultado de cada acção executada."""

    action_id: str
    status: Literal["done", "failed", "skipped"]
    error: str | None = None


class FaqExecuteResponse(BaseModel):
    """Resposta do POST /chat/faq/execute."""

    summary: dict[str, int]          # {done, failed, skipped}
    results: list[FaqExecuteActionResult]
    text: str                        # resumo em PT-BR
