# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository. Read this end-to-end before making changes. Keep it updated whenever architecture, conventions, or commands change.

---

## 1. What this project is

A chat application that:

1. Ingests PDFs into a knowledge graph + vector store.
2. Answers questions about the uploaded content (RAG).
3. Generates 20,000+ word structured handbooks via an AgentWrite-style plan-then-write pipeline (LongWriter technique).

It is the deliverable for the **LunarTech AI Engineering Assignment** (`AI-Engineering-Assignment.pdf`, top-level `README.md`).

> The assignment materials and any generated handbooks are **LunarTech IP** — do not publish or share publicly.

---

## 2. Tech stack (locked)

| Layer            | Choice                                                   | Notes                                                       |
| ---------------- | -------------------------------------------------------- | ----------------------------------------------------------- |
| Frontend         | Vite + React + TypeScript + Tailwind                     | SPA in `frontend/`                                          |
| Backend          | FastAPI (Python 3.11+), Uvicorn                          | App in `backend/app/`                                       |
| LLM + embeddings | OpenRouter (`OPENROUTER_API_KEY`, OpenAI-compatible API) | Default chat: `openrouter/free`; `services/openrouter.py`   |
| RAG              | LightRAG                                                 | Hybrid retrieval (`mode="hybrid"`)                          |
| KV + Vector      | Supabase Postgres + pgvector                             | Via LightRAG's `PostgresKVStorage` / `PostgresVectorStorage` |
| Graph storage    | LightRAG default NetworkX JSON in `working_dir/`         | Supabase has no Apache AGE                                  |
| PDF parsing      | `pypdf` primary, `pdfplumber` fallback                   |                                                             |
| Streaming        | Server-Sent Events (SSE) for chat + handbook             | `EventSource` on the client                                 |

Do **not** silently swap any of these without updating both `AGENTS.md` and `docs/PLAN.md`.

---

## 3. Repository layout

```
backend/
  app/
    main.py              # FastAPI factory, CORS, lifespan (init LightRAG once)
    config.py            # Pydantic settings, env loading, client factories
    schemas.py           # Pydantic request/response models
    routes/
      upload.py          # POST /upload         (PDF -> extract -> insert)
      chat.py            # POST /chat   (SSE)   hybrid RAG + LLM streaming
      handbook.py        # POST /handbook (SSE) AgentWrite pipeline
      documents.py       # GET  /documents      list ingested PDFs
    services/
      pdf.py             # extraction + cleanup
      rag.py             # LightRAG singleton wired to Supabase + OpenRouter LLM + embed
      openrouter.py      # AsyncOpenAI client for OpenRouter (chat + embeddings)
      agentwrite.py      # plan() + write_segments() with $CONTEXT$ injection
  supabase/schema.sql    # pgvector extension + LightRAG tables + documents table
  requirements.txt
  .env.example
frontend/
  src/
    App.tsx
    api.ts               # fetch + EventSource helpers
    components/
      Uploader.tsx
      DocumentList.tsx
      Chat.tsx
      HandbookView.tsx
  package.json
  vite.config.ts
docs/
  PLAN.md                # phased build plan + verify gates
  writeup.md             # required submission write-up
  demo/                  # screenshots / screen recording
LongWriter-main/         # READ-ONLY reference implementation. Do not modify.
Documentation/           # READ-ONLY assignment + research paper
AGENTS.md                # this file
README.md                # top-level: assignment + setup instructions
```

Rules:

- `LongWriter-main/` and `Documentation/` are reference material — never edit them. Copy snippets into our own modules instead.
- New backend modules go under `backend/app/`. New frontend code under `frontend/src/`.
- One responsibility per service module; routes stay thin (parse request → call service → return).

---

## 4. Environment variables

Defined in `backend/.env.example`. Never commit real values.

| Var                       | Required | Purpose                                                 |
| ------------------------- | :------: | ------------------------------------------------------- |
| `OPENROUTER_API_KEY`      |    ✅    | Chat + embeddings (OpenAI-compatible base URL)         |
| `OPENROUTER_BASE_URL`     |          | Defaults to `https://openrouter.ai/api/v1`              |
| `OPENROUTER_CHAT_MODEL`   |          | Defaults to `openrouter/free` (zero-cost chat router)    |
| `OPENROUTER_EMBED_MODEL`  |          | Defaults to `openai/text-embedding-3-small` (see pricing) |
| `OPENROUTER_HTTP_REFERER` |          | Optional; OpenRouter attribution header                  |
| `OPENROUTER_APP_TITLE`    |          | Optional; defaults to `Handbook Generator`               |
| `SUPABASE_DB_URL`         |    ✅    | `postgresql://postgres:<pwd>@<host>:5432/postgres`      |
| `SUPABASE_URL`         |          | Optional, only if storing raw PDFs in Supabase Storage  |
| `SUPABASE_SERVICE_KEY` |          | Optional, pairs with `SUPABASE_URL`                     |
| `LIGHTRAG_WORKING_DIR` |          | Defaults to `backend/.lightrag/`                        |
| `CORS_ORIGINS`         |          | Comma-separated, defaults to `http://localhost:5173`    |

Load via `pydantic-settings`. Fail fast on missing required vars in `config.py`.

---

## 5. Commands

Run from repo root unless noted. If your shell is already in `backend/` (the prompt ends with `backend %` or similar), skip `cd backend` and run `uvicorn` / `pip` from there.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then fill in keys
uvicorn app.main:app --reload --port 8000

# Supabase schema (one-time, after creating the project + enabling pgvector)
psql "$SUPABASE_DB_URL" -f backend/supabase/schema.sql

# Frontend
cd frontend
npm install
npm run dev                # http://localhost:5173

# Lint / format (from repo root)
cd backend && .venv/bin/ruff check app && .venv/bin/ruff format app
npm --prefix frontend run lint
npm --prefix frontend run build
```

If you add new commands (tests, migrations, etc.), document them here.

---

## 6. AgentWrite domain knowledge

The handbook generator implements the LongWriter "AgentWrite" pipeline (see `Documentation/Unleashing 10000 Word Generation From Long Context.pdf` and `LongWriter-main/agentwrite/`). Key points to preserve when changing this code:

### Planner stage

- Input: user's handbook instruction + retrieved high-level context.
- Output: one paragraph per line, each with a `Main Point` and `Word Count`.
- Constraint from the original prompt: each paragraph must be **200–1000 words**. We additionally instruct the planner to target **>= 22,000 total words** to leave headroom for the 20k floor.
- Source prompt: `LongWriter-main/agentwrite/prompts/plan.txt` — copy verbatim into `backend/app/services/agentwrite.py`, do not paraphrase.

### Writer stage

- **Serial, never parallel.** The paper shows parallel writing reduces coherence. Preserve sequential execution even when tempted to speed it up.
- For paragraph `n`, the prompt contains: original instruction, full plan, all previously generated text, the current step, and (our addition) `$CONTEXT$` from LightRAG retrieval scoped to the step.
- Output: only the new paragraph, no repetition of prior text, no open-ended hooks.
- Source prompt: `LongWriter-main/agentwrite/prompts/write.txt` — copy verbatim and append a `Relevant context from uploaded PDFs:\n$CONTEXT$` block.

### Post-processing

- Strip leading scaffolding the LLM may emit (`Paragraph N`, `Main Point:`, `Word Count:`, leading bullet markers).
- Count words after the loop. If `< 20,000`, run an **expansion pass** that asks the LLM (via OpenRouter) to extend the shortest paragraphs with additional cited content from LightRAG until the threshold is met. Hard cap total at ~30,000 to control cost.

### Evaluation expectations (from the paper)

- Length adherence is piecewise-linear: penalized if output `< L/3` or `> 4L`. Aim for `L ∈ [20k, 25k]`.
- Quality dimensions: Relevance, Accuracy, Coherence, Clarity, Breadth/Depth, Reading Experience. Optimize prompts and retrieval, not raw token count.

---

## 7. Coding conventions

### Python

- Python 3.11+. Type-annotate every public function. Use `from __future__ import annotations` only when needed for forward refs.
- `async def` for anything that touches the network (OpenRouter, Supabase, LightRAG queries). Never block the event loop with `requests`/`time.sleep` — use `httpx`/`asyncio`.
- Use `pydantic` v2 models for request/response schemas in `schemas.py`.
- Logging via `logging.getLogger(__name__)`. No `print` in committed code.
- Prefer composition over inheritance. One class per file when the class is non-trivial.
- No comments that narrate code. Comments only for non-obvious intent or constraints.

### TypeScript / React

- Functional components + hooks only.
- API calls live in `frontend/src/api.ts`. Components never call `fetch` directly.
- Use `react-markdown` (+ `remark-gfm`) for handbook rendering.
- Tailwind for styling. No CSS modules unless justified.
- Keep components < ~200 lines; split when growing.

### Streaming

- Backend SSE format: each event is `event: <type>\ndata: <json>\n\n`. Event types:
  - Chat: `token`, `done`, `error`.
  - Handbook: `plan_ready`, `paragraph`, `expanding`, `done`, `error`.
- Frontend uses `EventSource` and switches on `event.type`.

### Errors

- Backend raises `HTTPException` with a clear `detail`. Unexpected errors: log with stack, return `500` with a generic message.
- Frontend surfaces errors in the chat thread or as a toast — never silent failure.

---

## 8. Things to be careful about

- **Cost / runtime**: handbook generation can be 30+ LLM calls, each up to 4k tokens out. Always log per-call latency + token usage. Provide a cancel button on the frontend; honor it server-side via `request.is_disconnected()`.
- **LightRAG init is expensive** — initialize once in the FastAPI lifespan, not per request.
- **OpenAI embedding rate limits** — batch chunks (e.g. 64 per call) when ingesting large PDFs.
- **Supabase connection pool** — use `asyncpg` pool, not a fresh connection per query.
- **Idempotent uploads** — hash PDF bytes; if hash already ingested, skip re-embedding.
- **Don't leak keys** — `.env` is gitignored; `OPENROUTER_API_KEY` never goes to the frontend.
- **Cancellation**: long handbook runs must check disconnect every paragraph; otherwise we keep paying for tokens nobody will read.

---

## 9. Definition of done (per submission checklist)

- [ ] Working app runs locally with documented setup.
- [ ] PDF upload works for at least the provided LongWriter paper.
- [ ] Chat returns answers grounded in uploaded content.
- [ ] Handbook endpoint produces `>= 20,000` words, with TOC, headings, and citations.
- [ ] Demo screenshots or screen recording in `docs/demo/`.
- [ ] `docs/writeup.md` covers what was built, approach, challenges.
- [ ] Top-level `README.md` setup section updated.

---

## 10. When you finish a task

1. Run `cd backend && .venv/bin/ruff check app` and `npm --prefix frontend run build` — both must pass.
2. Update the relevant phase checklist in `docs/PLAN.md`.
3. If you changed architecture, conventions, env vars, or commands, update this file in the same change.
4. Do not commit unless the user explicitly asks.


## Coding standards

1. Use latest versions of libraries and idiomatic approaches as of today
2. Keep it simple - NEVER over-engineer, ALWAYS simplify, NO unnecessary defensive programming. No extra features - focus on simplicity.
3. Be concise. Keep README minimal. IMPORTANT: no emojis ever
4. When hitting issues, always identify root cause before trying a fix. Do not guess. Prove with evidence, then fix the root cause.

## Working documentation

All documents for planning and executing this project will be in the docs/ directory.
Please review the docs/PLAN.md document before proceeding.