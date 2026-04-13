"""
schemas/report_types.py — Entidades e filtros disponíveis para relatórios.

O report_agent interpreta linguagem natural e mapeia para uma dessas entidades.
Cada entidade define o endpoint da eleve-api e as colunas do arquivo gerado.
"""
from __future__ import annotations

REPORT_ENTITIES: dict[str, dict] = {
    "inadimplencia": {
        "label": "Inadimplência",
        "description": "Alunos com mensalidades em atraso",
        "endpoint": "/api/v1/contacts/guardians/{guardian_id}/invoices/",
        "strategy": "per_guardian",          # requer iteração por responsável
        "columns": [
            "student_name", "grade", "guardian_name",
            "amount", "due_date", "days_overdue",
        ],
        "filters": ["month", "grade", "status"],
        "keywords": ["inadimplente", "atraso", "devedor", "não pagou", "vencido"],
    },
    "matriculas": {
        "label": "Matrículas",
        "description": "Matrículas ativas ou novas",
        "endpoint": "/api/v1/secretary/enrollments/",
        "strategy": "direct",
        "columns": [
            "student_name", "grade", "guardian_name",
            "enrollment_date", "status", "monthly_fee",
        ],
        "filters": ["year", "grade", "status", "month"],
        "keywords": ["matrícula", "matriculado", "novo aluno", "enrollment"],
    },
    "solicitacoes": {
        "label": "Solicitações",
        "description": "Solicitações abertas na secretaria",
        "endpoint": "/api/v1/requests/",
        "strategy": "direct",
        "columns": [
            "protocol", "request_type", "student_name",
            "guardian_name", "created_at", "status",
        ],
        "filters": ["request_type", "status", "month"],
        "keywords": ["solicitação", "protocolo", "pedido", "secretaria", "documento"],
    },
    "frequencia": {
        "label": "Frequência",
        "description": "Frequência de alunos por turma",
        "endpoint": "/api/v1/requests/",
        "strategy": "direct",
        "query_params": {"tipo": "declaracao", "subtype": "frequencia"},
        "columns": [
            "student_name", "grade", "attendance_pct",
            "absences", "period",
        ],
        "filters": ["grade", "month", "year"],
        "keywords": ["frequência", "falta", "presença", "ausência", "infrequente"],
    },
}


def infer_entity(prompt: str) -> str | None:
    """
    Tenta inferir a entidade pelo prompt em linguagem natural.
    Retorna a chave da entidade ou None se não reconhecer.
    """
    prompt_lower = prompt.lower()
    for entity_key, entity in REPORT_ENTITIES.items():
        if any(kw in prompt_lower for kw in entity["keywords"]):
            return entity_key
    return None


def get_entity(entity_key: str) -> dict:
    if entity_key not in REPORT_ENTITIES:
        valid = ", ".join(REPORT_ENTITIES.keys())
        raise ValueError(f"Entidade '{entity_key}' inválida. Use: {valid}")
    return REPORT_ENTITIES[entity_key]


SUPPORTED_ENTITIES  = list(REPORT_ENTITIES.keys())
SUPPORTED_FORMATS   = ["xlsx", "docx"]
