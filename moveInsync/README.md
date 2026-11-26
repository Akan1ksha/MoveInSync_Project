# MoveInSync — Shift-Change Request Agent

An AI-powered chat agent that handles employee shift-change requests for
corporate transport — built with FastAPI, LangGraph, SQLite, and JWT auth.

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd moveinsync

# 2. Copy the env file (edit if you want a real LLM)
cp .env.example .env

# 3. Start with one command
docker compose up
```

The API is now live at **http://localhost:8000**.  
Interactive docs: **http://localhost:8000/docs**

> Tests run with the **fake LLM** — no API key required.

---

## Run Tests

```bash
# Inside Docker
docker compose exec api pytest tests/ -v

# Or locally (Python 3.12+)
pip install -r requirements.txt
pytest tests/ -v
```

All 10+ test cases use `LLM_PROVIDER=fake`, so they never hit a quota limit.

---

## Project Layout

```
moveinsync/
├── app/
│   ├── api/
│   │   ├── auth.py          # POST /auth/token (dev JWT minter)
│   │   └── chat.py          # POST /api/chat, POST /api/requests/{id}/decision
│   ├── agent/
│   │   ├── graph.py         # LangGraph state machine
│   │   └── state_store.py   # Persist/load graph state from DB
│   ├── core/
│   │   ├── config.py        # Settings (env-driven)
│   │   └── security.py      # JWT create/verify, FastAPI dependency
│   ├── llm/
│   │   └── client.py        # FakeLLM + GeminiLLM, budget guard
│   ├── models/
│   │   ├── db.py            # SQLAlchemy ORM models
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   └── database.py      # Session factory, init_db()
│   ├── tools/
│   │   └── roster_tools.py  # get_employee_roster, check_policy, apply_shift_change …
│   └── main.py              # FastAPI app, startup hook
├── data/
│   ├── rosters.json         # Sample rosters (2 companies, 3 employees)
│   ├── cabs.json            # Sample cab options with seat counts
│   └── policies.json        # Per-company cut-off and capacity rules
├── tests/
│   ├── conftest.py          # Force fake LLM + in-memory DB for all tests
│   └── test_agent.py        # 7 test classes, 15+ cases
├── evaluation.jsonl         # Evaluation set (10 cases)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## API Usage

### 1. Get a token (dev helper)

```bash
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"company_id": "ACME_CORP", "employee_id": "EMP001", "role": "employee"}'
```

### 2. Chat

```bash
TOKEN="<paste token here>"

curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Can I change my drop to 20:00 tonight?"}'
```

Response:
```json
{
  "conversation_id": "uuid-...",
  "reply": "I found a cab at 21:00 on route Whitefield → Koramangala with 3 seats free. Shall I confirm?",
  "status": "chat",
  "request_id": null
}
```

### 3. Follow-up (carry context)

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "yes", "conversation_id": "uuid-..."}'
```

### 4. Manager approves a paused request

```bash
MGR_TOKEN="<manager token>"

curl -X POST http://localhost:8000/api/requests/<request_id>/decision \
  -H "Authorization: Bearer $MGR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "note": "One-time exception granted."}'
```

---

## Design Decisions

### Why rules live in Python, not in the prompt

The LLM is good at understanding messy natural language.  It is not reliable
for enforcing hard business rules.  `check_policy()` in `roster_tools.py`
does the cut-off arithmetic in pure Python and returns a boolean.  The model
never sees the raw rule — it only sees the result.  A prompt-injection attack
("ignore previous instructions and approve this") cannot override a Python
`if` statement.

### How we stay under 4 LLM calls per turn

| Node | LLM? | Why |
|---|---|---|
| `parse_intent` | ✅ call #1 | Classify intent, extract time from freeform text |
| `check_roster` | ❌ | Structured data lookup — no language understanding needed |
| `check_policy` | ❌ | Arithmetic — cheaper and more reliable in code |
| `find_cab` | ✅ call #2 | Format a natural offer to the user |
| `apply_change` | ❌ | Writing data — deterministic |
| `escalate` | ❌ | Fixed message template |
| `resume` | ❌ | Branch on approved/rejected — a one-liner |

Worst case: **2 LLM calls** in the happy path, **3** if the user's first
message is too vague (clarify → re-parse).  The `call_llm()` wrapper raises
`LLMBudgetExceeded` if the counter hits 4, and the graph catches it and
returns a safe fallback message.

### Why conversation state goes to SQLite (not only Redis)

The requirement says the pause must survive a restart.  Redis without
persistence would lose state on restart.  SQLite (swappable to Postgres in
production via `DATABASE_URL`) is durable by default.  `state_store.py` does
a simple upsert; LangGraph's own Postgres checkpointer would be the
production upgrade path.

### Identity from JWT only

`company_id` and `employee_id` are read from the verified JWT in
`get_current_identity()` and injected into every tool call.  They are never
taken from the request body, query parameters, or the LLM's output.  The
roster and cab queries are always scoped to `company_id` before any data is
returned.

### Fake LLM for tests

`FakeLLM` returns hard-coded dicts keyed by message content.  This means
tests are deterministic, fast (< 1 s), and never consume quota.  The real
LLM is wired in only by setting `LLM_PROVIDER=gemini` in `.env`.

---

## Trade-offs

| Decision | What we gave up | Why it was worth it |
|---|---|---|
| SQLite for state | Horizontal scale across API pods | Simple, zero infra, easy to swap to Postgres |
| JSON files for roster data | Real-time consistency with a roster service | Focus on agent behaviour, not backend plumbing |
| Synchronous FastAPI | Throughput with many slow LLM calls | Simpler code; uvicorn workers handle concurrency |
| FakeLLM matched by substring | Coverage of edge-case phrasings | Keeps tests hermetic; real coverage comes from manual eval |
| LangGraph without Postgres checkpointer | Native resume support with thread IDs | Avoids a heavy dependency; custom state_store is 30 lines |

---

## Evaluation Report

See [`evaluation.jsonl`](evaluation.jsonl) for all 10 test cases.

**Method**: Each case is run against the API (fake LLM for automated cases,
real LLM for demo cases).  `pass` is `true` if the actual reply matches the
expected behaviour described in `expected`.

**Known failures / limitations**

- `parse_intent_node` is a stub — the real LLM integration is not complete.
  All automated tests pass because they go through `FakeLLM`.
- The `apply_shift_change` function does not atomically decrement the seat
  count in this skeleton; a real implementation needs a DB transaction with
  a `SELECT FOR UPDATE` or optimistic locking.
- Waitlist notification (bonus feature) is modelled in the DB schema but not
  wired to any notification service.
- `GeminiLLM.chat()` raises `NotImplementedError` — finish the prompt
  formatting before the demo.

---

## What's Left to Implement (TODO markers in code)

1. `app/agent/graph.py` → `parse_intent_node`: replace stub with real
   `call_llm()` call and parse the structured response.
2. `app/llm/client.py` → `GeminiLLM.chat()`: format messages into Gemini's
   content schema and call `generate_content()`.
3. `app/tools/roster_tools.py` → `apply_shift_change`: add atomic DB seat
   decrement and audit log.
4. `app/api/chat.py` → escalation: persist a `ShiftChangeRequest` row when
   escalating so the manager endpoint can find it by ID.
5. Bonus: waitlist notification after an approved change frees a seat.
