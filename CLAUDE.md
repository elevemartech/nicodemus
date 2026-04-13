# CLAUDE.md — Nicodemus ADM

Contexto permanente para o Claude Code. **Leia inteiro antes de qualquer tarefa.**

> Este arquivo é a fonte de verdade arquitetural do projeto.
> Toda decisão de design que não está aqui é uma decisão não tomada — e vai virar bug.

---

## 1. O que é este projeto

Microserviço Python (**FastAPI + LangGraph**) que opera como copiloto de gestão escolar
no painel administrativo da plataforma **Eleve**.

**Não é o eleve-agent.** Não processa WhatsApp. Não atende pais.
Serve exclusivamente gestores autenticados (diretores, secretaria, admin, manager).

Faz três coisas:

```
LER       → Recebe documento (PDF/imagem), extrai dados via GPT-4o Vision,
             valida contra a eleve-api e registra após revisão humana.

RELATAR   → Recebe pedido em linguagem natural, consulta a eleve-api,
             gera arquivo .xlsx ou .docx e entrega para download.

CONVERSAR → Mantém sessões conversacionais persistentes com memória Redis
             e histórico PostgreSQL. Agente ReAct em agent/nico_agent.py.
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
LangGraph            → StateGraph por fluxo (doc_reader, report_agent, nico_agent)
LangChain + OpenAI   → LLM (gpt-4o-mini), vision (gpt-4o)
openpyxl             → geração de .xlsx
python-docx          → geração de .docx
SQLAlchemy async     → ORM para sessões e mensagens (PostgreSQL)
asyncpg              → driver PostgreSQL assíncrono
Alembic              → migrações de banco de dados
Redis                → contexto conversacional (últimas 20 mensagens, TTL 24h)
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
  → extrai { user_id, school_id, role, sa_token, name }
  → role deve ser: "director" | "secretary" | "admin" | "manager"
  → sa_token é usado para chamar a eleve-api (isolamento multi-tenant)
  → name é usado para personalização das respostas do agente
```

O `sa_token` SEMPRE vem do JWT. Nunca é gerado aqui.

**Nunca aceite requisição sem JWT válido.**
**Nunca aceite role fora de ["director", "secretary", "admin", "manager"].**

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

POST /sessions/
  → Cria nova sessão conversacional
  → Retorna: session_id, title, status

GET /sessions/
  → Lista sessões do gestor autenticado (ordenadas por last_activity_at)

GET /sessions/{id}/
  → Detalhe da sessão + últimas 50 mensagens

POST /sessions/{id}/close/
  → Encerra sessão e gera resumo via LLM

DELETE /sessions/{id}/
  → Soft delete (is_deleted=True)

POST /chat/
  → Recebe: { session_id, message }
  → Processa mensagem via NicoAgent (ReAct)
  → Retorna: { session_id, reply, file_id?, file_url? }
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

## 7. Relatórios disponíveis (report_agent e NicoAgent)

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

### agents/state.py — NicoState (doc_reader e report_agent)

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

### agent/state.py — NicoState (NicoAgent conversacional)

**DIFERENTE do anterior.** Este é o estado do agente ReAct com memória de sessão.

```python
class NicoState(TypedDict, total=False):
    user_id:      str
    school_id:    str
    sa_token:     str
    role:         str
    user_name:    str      # nome do gestor (personalização)
    session_id:   str
    messages:     list[dict]   # formato OpenAI, serializável para Redis
    user_message: str
    tool_calls:   list[dict]
    response:     str
    error:        str | None
```

**ATENÇÃO:** Nunca importe os dois `NicoState` no mesmo arquivo. Use o caminho
completo do import para distinguir: `from agent.state import NicoState` vs
`from agents.state import NicoState`.

---

## 10. Arquitetura conversacional

### Sessões (PostgreSQL)

```
models/session.py → ManagerSession
  id, user_id, school_id, role, user_name
  title (default "Nova conversa"), status (active/paused/completed)
  summary, is_deleted, message_count, report_count
  created_at, last_activity_at, ended_at

models/message.py → ManagerMessage
  id, session_id (FK), role (user/assistant/tool)
  content, tool_calls (JSON), metadata_ → coluna "metadata" (JSON)
  created_at
```

Migrations em `alembic/versions/`. Aplicar com:
```bash
poetry run alembic upgrade head
```

### Memória Redis (core/memory.py)

```
Key:   nicodemus:context:{session_id}
Valor: JSON list, máximo 20 mensagens, TTL 24h

get_context(session_id) → list[dict]
set_context(session_id, messages)
append_turn(session_id, user_msg, assistant_msg)
rebuild_from_db(session_id, messages)
clear_context(session_id)
```

### NicoAgent ReAct (agent/nico_agent.py)

```
StateGraph: llm_node → should_use_tools → tool_node → llm_node (loop) | END

llm_node:   converte messages list[dict] → LangChain messages → gpt-4o-mini
tool_node:  injeta sa_token + school_id em cada tool call
TOOLS_REGISTRY (agent/tools/__init__.py):
  - generate_financial_report  (inadimplência)
  - generate_enrollments_report (matrículas)
  - generate_requests_report   (solicitações)
```

### SessionService (services/session_service.py)

Métodos estáticos que recebem `db: AsyncSession`. Usam `flush()`, nunca `commit()`.

```
create_session(db, user_id, school_id, role, user_name) → ManagerSession
get_or_resume(db, session_id, user_id) → ManagerSession
add_message(db, session, role, content, tool_calls, metadata) → ManagerMessage
set_title(db, session, title)         # só atualiza se title == "Nova conversa"
close_session(db, session, summary)   # status=completed, limpa Redis
increment_report_count(db, session)
```

---

## 11. Regras de negócio

1. **Revisão humana obrigatória** antes de qualquer PATCH/POST na eleve-api
2. **Confidence < 0.80** → marcar flag e forçar revisão campo a campo
3. **Arquivo gerado expira em 15 minutos** — nunca armazenar permanentemente
4. **Log de toda ação** com `user_id`, `school_id` e `action` para auditoria
5. **Erros de extração** → retornar campos parciais + lista de flags, nunca exception 500
6. **Relatório vazio** → retornar `{ summary: "Nenhum registro encontrado", data: [] }`
   — nunca gerar arquivo em branco
7. **Sessão encerrada** → rejeitar POST /chat/ com 400, exigir nova sessão
8. **Contexto Redis vazio** (sessão retomada) → reconstruir a partir do banco automaticamente

---

## 12. Variáveis de ambiente

| Variável           | Descrição |
|---|---|
| `ELEVE_API_URL`    | URL da Eleve API |
| `OPENAI_API_KEY`   | Chave OpenAI |
| `JWT_SECRET`       | Secret para validar JWT do dashboard |
| `JWT_ALGORITHM`    | Algoritmo JWT (default: HS256) |
| `REDIS_URL`        | URL do Redis |
| `FILE_STORAGE_TTL` | TTL dos arquivos gerados em segundos (default: 900) |
| `FILE_STORAGE_DIR` | Diretório temporário (default: /tmp) |
| `DATABASE_URL`     | URL PostgreSQL async (ex: postgresql+asyncpg://...) |

---

## 13. Gotchas críticos do SQLAlchemy async

1. **`expire_on_commit=False`** em `async_sessionmaker` — evita `MissingGreenlet` ao
   acessar atributos após commit fora do contexto da sessão.

2. **`lazy="select"` em todos os relacionamentos** — nunca usar `lazy="joined"` em async.
   Sempre fazer queries explícitas ao precisar de dados relacionados.

3. **`metadata_` ≠ `metadata`** — a coluna `metadata` em `ManagerMessage` usa o atributo
   Python `metadata_` porque `metadata` é atributo reservado do `DeclarativeBase`.

4. **`flush()` nos services, `commit()` no get_session** — services chamam `flush()` para
   obter IDs gerados sem encerrar a transação. O `get_session` dependency faz o commit.

5. **`alembic/env.py` deve ser async** — o arquivo gerado por `alembic init` é síncrono.
   O env.py deste projeto usa `asyncio.run()` + `create_async_engine`.
