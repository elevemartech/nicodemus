# CLAUDE.md — Nicodemus ADM

Contexto permanente para o Claude Code. **Leia inteiro antes de qualquer tarefa.**

> Este arquivo é a fonte de verdade arquitetural do projeto.
> Toda decisão de design que não está aqui é uma decisão não tomada — e vai virar bug.

---

## 1. O que é este projeto

Microserviço Python (**FastAPI + LangGraph**) que opera como copiloto de gestão escolar
no painel administrativo da plataforma **Eleve**.

**Não é o eleve-agent.** Não processa WhatsApp. Não atende pais.
Serve exclusivamente gestores autenticados (diretores, secretaria, admin).

Faz duas coisas:

```
LER       → Recebe documento (PDF/imagem), extrai dados via GPT-4o Vision,
             valida contra a eleve-api e registra após revisão humana.

RELATAR   → Recebe pedido em linguagem natural, consulta a eleve-api,
             gera arquivo .xlsx ou .docx e entrega para download.
```

---

## 2. Repositório irmão

API Django em `../eleve-api`. Leia os arquivos diretamente quando precisar
entender endpoints, serializers ou models.

Caminhos úteis:
```
../eleve-api/apps/requests/models.py
../eleve-api/apps/requests/choices.py
../eleve-api/apps/contacts/views/guardian_viewset.py
../eleve-api/apps/contacts/serializers/invoice_serializers.py
../eleve-api/apps/secretary/models.py
../eleve-api/apps/schools/models.py
../eleve-api/config/urls.py
```

---

## 3. Stack

```
FastAPI + uvicorn     → endpoints REST (não webhook)
LangGraph            → StateGraph por fluxo (doc_reader, report_agent)
LangChain + OpenAI   → LLM (gpt-4o-mini), vision (gpt-4o)
openpyxl             → geração de .xlsx
python-docx          → geração de .docx
Redis                → cache de sa_token por school_id (TTL 1h)
httpx                → cliente HTTP assíncrono para a eleve-api
Poetry               → gerenciamento de dependências
```

---

## 4. Autenticação — CRÍTICO

O eleve-agent usa `ServiceKey` de WhatsApp.
**O Nicodemus ADM usa JWT do usuário logado no dashboard.**

```
Dashboard → Authorization: Bearer <jwt_do_usuario>
  → core/auth.py valida JWT
  → extrai { user_id, school_id, role, sa_token }
  → role deve ser: "director" | "secretary" | "admin"
  → sa_token é usado para chamar a eleve-api (isolamento multi-tenant)
```

O `sa_token` pode vir embutido no JWT ou ser resolvido via Redis/eleve-api
pelo `school_id`. Ver `core/auth.py` para implementação atual.

**Nunca aceite requisição sem JWT válido.**
**Nunca aceite role fora de ["director", "secretary", "admin"].**

---

## 5. Endpoints

```
POST /doc/extract
  → Recebe: multipart (arquivo) + doc_type
  → Retorna: campos extraídos + confidence + flags de validação
  → Agente: doc_reader_agent
  → NÃO persiste nada — só extrai e valida. A secretaria confirma antes.

POST /doc/confirm
  → Recebe: extraction_id + campos corrigidos
  → Persiste na eleve-api via patch_request
  → Gera protocolo SEC- ou FIN-

POST /report/generate
  → Recebe: prompt em linguagem natural + format ("xlsx" | "docx")
  → Retorna: file_url (TTL 15min) + summary + preview[]
  → Agente: report_agent

GET /report/download/{file_id}
  → Serve o arquivo gerado (redirect ou stream)
```

---

## 6. Tipos de documento suportados

```python
# schemas/doc_types.py

DOC_TYPES = {
    "comprovante_pagamento": {
        "fields": ["payer_name", "amount", "payment_date", "bank", "student_name"],
        "eleve_request_type": "comprovante_pagamento",   # FIN-
    },
    "contrato_matricula": {
        "fields": ["guardian_name", "student_name", "grade", "start_date", "monthly_fee"],
        "eleve_request_type": "rematricula",              # SEC-
    },
    "boletim": {
        "fields": ["student_name", "grade", "year", "subjects"],
        "eleve_request_type": "outros",                   # SEC- (endpoint futuro)
    },
}
```

---

## 7. Relatórios disponíveis (report_agent)

O agente interpreta linguagem natural e mapeia para entidades da eleve-api:

| Entidade        | Endpoint eleve-api                              |
|---|---|
| inadimplência   | GET /contacts/guardians/{id}/invoices/?status=overdue |
| matrículas      | GET /secretary/enrollments/                     |
| frequência      | GET /requests/?tipo=declaracao&subtype=frequencia |
| solicitações    | GET /requests/                                  |
| leads           | inferido via GET /requests/ (tipo MAT-)         |

Formatos de saída: `xlsx` (openpyxl) ou `docx` (python-docx).

---

## 8. Convenção de tool

Segue o mesmo padrão do eleve-agent:

```python
@tool
async def nome_da_tool(param: str, sa_token: str, **kwargs) -> str:
    """Descrição em uma linha — o LLM usa isso para decidir quando chamar."""
    async with DjangoAPIClient(token=sa_token) as client:
        try:
            result = await client.get("/api/v1/endpoint/")
            return "Resultado formatado como texto ou JSON string"
        except Exception as e:
            logger.error("tool_name.error", error=str(e))
            return ""
```

---

## 9. AgentState

```python
class NicoState(TypedDict, total=False):
    # comum
    user_id:    str
    school_id:  str
    sa_token:   str
    role:       str

    # doc_reader_agent
    doc_type:        str
    raw_file_b64:    str
    extracted:       dict
    validated:       dict
    confidence:      float
    flags:           list[str]
    extraction_id:   str

    # report_agent
    user_prompt:     str
    report_plan:     dict
    report_data:     list[dict]
    file_format:     str        # "xlsx" | "docx"
    file_path:       str
    file_id:         str
    summary:         str

    # saída
    response:        str
    error:           str | None
```

---

## 10. Regras de negócio

1. **Revisão humana obrigatória** antes de qualquer PATCH/POST na eleve-api
2. **Confidence < 0.80** → marcar flag e forçar revisão campo a campo
3. **Arquivo gerado expira em 15 minutos** — nunca armazenar permanentemente
4. **Log de toda ação** com `user_id`, `school_id` e `action` para auditoria
5. **Erros de extração** → retornar campos parciais + lista de flags, nunca exception 500
6. **Relatório vazio** → retornar `{ summary: "Nenhum registro encontrado", data: [] }`
   — nunca gerar arquivo em branco

---

## 11. Variáveis de ambiente

| Variável           | Descrição |
|---|---|
| `ELEVE_API_URL`    | URL da Eleve API |
| `OPENAI_API_KEY`   | Chave OpenAI |
| `JWT_SECRET`       | Secret para validar JWT do dashboard |
| `JWT_ALGORITHM`    | Algoritmo JWT (default: HS256) |
| `REDIS_URL`        | URL do Redis |
| `FILE_STORAGE_TTL` | TTL dos arquivos gerados em segundos (default: 900) |
| `FILE_STORAGE_DIR` | Diretório temporário (default: /tmp) |
