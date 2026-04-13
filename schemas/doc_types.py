"""
schemas/doc_types.py — Definição dos tipos de documento suportados.

Cada tipo define:
  - fields: campos que o GPT-4o Vision deve extrair
  - required: campos obrigatórios (confidence < 1.0 vira flag)
  - eleve_request_type: tipo de Request a criar na eleve-api após confirmação
  - prompt_hint: instrução extra para o modelo de visão
"""
from __future__ import annotations

DOC_TYPES: dict[str, dict] = {
    "comprovante_pagamento": {
        "label": "Comprovante de pagamento",
        "fields": [
            "payer_name",
            "amount",
            "payment_date",
            "bank",
            "student_name",
            "description",
        ],
        "required": ["payer_name", "amount", "payment_date"],
        "eleve_request_type": "comprovante_pagamento",   # → protocolo FIN-
        "prompt_hint": (
            "É um comprovante bancário ou recibo de pagamento escolar. "
            "Extraia: nome do pagador, valor pago (número), data do pagamento "
            "(formato YYYY-MM-DD), nome do banco/instituição, nome do aluno se visível, "
            "e descrição/histórico da transação."
        ),
    },
    "contrato_matricula": {
        "label": "Contrato / Termo de matrícula",
        "fields": [
            "guardian_name",
            "guardian_cpf",
            "student_name",
            "grade",
            "start_date",
            "monthly_fee",
            "school_name",
        ],
        "required": ["guardian_name", "student_name", "grade"],
        "eleve_request_type": "rematricula",             # → protocolo SEC-
        "prompt_hint": (
            "É um contrato ou termo de matrícula escolar. "
            "Extraia: nome completo do responsável, CPF do responsável (se visível), "
            "nome completo do aluno, série/ano escolar, data de início, "
            "valor da mensalidade (número) e nome da escola."
        ),
    },
    "boletim": {
        "label": "Boletim escolar",
        "fields": [
            "student_name",
            "grade",
            "school_year",
            "period",
            "subjects",       # lista: [{name, grade, frequency}]
        ],
        "required": ["student_name", "grade"],
        "eleve_request_type": "outros",                  # → protocolo SEC- (endpoint futuro)
        "prompt_hint": (
            "É um boletim ou histórico escolar. "
            "Extraia: nome do aluno, série/ano, ano letivo, bimestre/semestre, "
            "e uma lista de matérias com nota e frequência de cada uma. "
            "Retorne 'subjects' como array de objetos {name, grade, frequency}."
        ),
    },
}


def get_doc_type(doc_type: str) -> dict:
    """Retorna definição do tipo ou levanta ValueError."""
    if doc_type not in DOC_TYPES:
        valid = ", ".join(DOC_TYPES.keys())
        raise ValueError(f"Tipo '{doc_type}' inválido. Use: {valid}")
    return DOC_TYPES[doc_type]


SUPPORTED_DOC_TYPES = list(DOC_TYPES.keys())
