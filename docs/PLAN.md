# PLAN.md

Phased build plan for the Handbook Generator. Phases are dependency-ordered: each one assumes the previous phases are green. Inside a phase, tasks are also ordered. Acceptance criteria for every task are explicit so progress is verifiable.

When a task ships, tick its box here and (if relevant) update `AGENTS.md`.

> Reference material: `LongWriter-main/agentwrite/{plan,write}.py`, `LongWriter-main/agentwrite/prompts/{plan,write}.txt`, `Documentation/Unleashing 10000 Word Generation From Long Context.pdf`. Read these before Phase 6.

## How to verify a phase

Every phase ends with a **Verify Phase N** block: a short list of commands you can run plus the exact signal that means it passed. **Do not start the next phase until every check in the current phase's Verify block is green and its checkbox is ticked.** If a check fails, fix it inside the current phase rather than papering over it later.

Conventions:

- Commands assume you are at the repo root and that `backend/.venv` is activated for backend commands.
- `LONGWRITER_PDF` shorthand below: `Documentation/Unleashing 10000 Word Generation From Long Context.pdf`.
- For SSE checks we use `curl -N` (no buffering) so events stream live.
- Where a check needs a tiny one-off script, the script is included inline so you can copy-paste.

---

## Phase 0 — Project bootstrap

Goal: empty-but-runnable scaffolding for both backend and frontend.

- [x] **0.1 Repo hygiene**
  - Add `.gitignore` entries: `backend/.venv/`, `backend/.env`, `backend/.lightrag/`, `frontend/node_modules/`, `frontend/dist/`, `*.pyc`, `__pycache__/`, `docs/demo/*` (binary).
  - Acceptance: `git status` clean after a fresh `pip install` + `npm install`.
- [x] **0.2 Backend skeleton**
  - Create `backend/{app,supabase}/` and `backend/app/{routes,services}/` with `__init__.py` files.
  - `backend/requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `python-multipart`, `httpx`, `openai`, `pypdf`, `pdfplumber`, `lightrag-hku`, `asyncpg`, `psycopg[binary]`, `sse-starlette`, `tenacity`, `ruff` (dev).
  - `backend/.env.example` with all vars from `AGENTS.md` §4.
  - `backend/app/main.py`: minimal FastAPI app with `GET /health` returning `{status:"ok"}`.
  - Acceptance: `uvicorn app.main:app --reload` boots; `curl localhost:8000/health` returns ok.
- [x] **0.3 Frontend skeleton**
  - `npm create vite@latest frontend -- --template react-ts` then add Tailwind (`tailwindcss`, `postcss`, `autoprefixer` + config), `react-markdown`, `remark-gfm`.
  - `frontend/.env`: `VITE_API_BASE=http://localhost:8000`.
  - `App.tsx`: 3-pane shell (Documents | Chat | Handbook) with placeholder text.
  - Acceptance: `npm run dev` shows the shell; `npm run build` succeeds.
- [x] **0.4 CORS + API helper**
  - Backend: enable `CORSMiddleware` for `CORS_ORIGINS`.
  - Frontend: `src/api.ts` with `apiUrl(path)` and `openSse(path, body, handlers)` helpers.
  - Acceptance: frontend can hit `/health` and render the result.

### Verify Phase 0

- [x] Backend up: `curl -s localhost:8000/health` → `{"status":"ok"}` (with `uvicorn` running from `backend/`).
- [ ] Frontend up: open `http://localhost:5173` → see the 3-pane shell with placeholder text.
- [ ] Cross-talk: in the browser DevTools network tab, the frontend's call to `/health` succeeds (status 200, no CORS error).
- [x] Clean tree: `git status` shows no untracked files inside `backend/.venv/`, `frontend/node_modules/`, or `__pycache__/`.
- [x] Build green: `npm --prefix frontend run build` exits 0; `python -c "import app.main"` from `backend/` exits 0.

---

## Phase 1 — Configuration & secrets

Goal: typed config, fail-fast on missing keys, no secrets in code.

- [x] **1.1 `config.py` Settings class**
  - `pydantic-settings.BaseSettings` with all env vars, defaults, and validation.
  - Single `get_settings()` (cached) used everywhere.
  - Acceptance: missing `OPENROUTER_API_KEY` raises a clear startup error.
- [x] **1.2 Logging setup**
  - `app/logging_config.py` with JSON or key=value formatter, log level from env.
  - Wire in `main.py` lifespan.
  - Acceptance: requests log method, path, status, duration.

### Verify Phase 1

- [ ] Fail-fast: temporarily comment out `OPENROUTER_API_KEY` in `backend/.env`, restart `uvicorn` → server refuses to start with a message naming the missing var. Restore the key.
- [x] Defaults applied: `OPENROUTER_API_KEY=dummy python -c "from app.config import get_settings; s=get_settings(); print(s.openrouter_chat_model, s.openrouter_embed_model)"` prints `openrouter/free openai/text-embedding-3-small` (or whatever you chose as defaults).
- [x] Request logging: `curl -s localhost:8000/health` then check the uvicorn output — one line includes method=`GET`, path=`/health`, status=`200`, and a duration in ms.
- [x] No secrets in code: `rg -n "sk-|xai-" backend/app` returns no matches (use `grep` if `rg` is not installed).

---

## Phase 2 — Supabase schema

Goal: database is ready for LightRAG + our `documents` table before any code touches it.

- [x] **2.1 Provision project**
  - Create Supabase project, copy `SUPABASE_DB_URL` into `.env`.
  - Note the project in `docs/writeup.md` (region, plan).
- [x] **2.2 `backend/supabase/schema.sql`**
  - `create extension if not exists vector;`
  - `documents` table: `id uuid pk default gen_random_uuid()`, `filename text`, `sha256 text unique`, `pages int`, `char_count int`, `created_at timestamptz default now()`.
  - Index on `sha256`.
  - LightRAG's Postgres storages auto-create their own tables on first use; we don't pre-create them.
  - Acceptance: `psql "$SUPABASE_DB_URL" -f backend/supabase/schema.sql` runs cleanly twice (idempotent).
- [x] **2.3 `db.py` async pool**
  - `asyncpg` pool created in lifespan, exposed via dependency.
  - Acceptance: `GET /health` returns `db: ok` after pinging `select 1`.

### Verify Phase 2

- [ ] Extension installed: `psql "$SUPABASE_DB_URL" -c "\dx vector"` shows the extension as installed (or confirm in SQL Editor after running `schema.sql`).
- [ ] Table exists: `psql "$SUPABASE_DB_URL" -c "\d documents"` lists `id`, `filename`, `sha256`, `pages`, `char_count`, `created_at` (or **Table Editor** → `documents`).
- [ ] Idempotent: re-run `psql "$SUPABASE_DB_URL" -f backend/supabase/schema.sql` — no errors.
- [x] Pool wired: `curl -s localhost:8000/health` returns `{"status":"ok","db":"ok"}` (or equivalent), and stopping the DB makes that field flip to `"db":"down"` instead of crashing the server.

---

## Phase 3 — LLM client (OpenRouter, no UI yet)

Goal: a single tested entry point for every chat completion (via OpenRouter).

- [x] **3.1 `services/llm.py` (or extend `openrouter.py`)**
  - `class LlmClient` wrapping `openai.AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)` from `get_async_openrouter_client()`.
  - Methods: `complete(prompt, max_tokens=4096, temperature=0.7) -> str` and `stream(prompt, ...) -> AsyncIterator[str]`.
  - Retry with `tenacity` on transient errors; surface context-length errors immediately.
  - Acceptance: a throwaway `python -m app.services.llm "Say hi"` script returns text.
- [x] **3.2 Token + latency logging**
  - Log `model`, `prompt_tokens`, `completion_tokens`, `latency_ms` after each call.
  - Acceptance: visible in stdout during the smoke test.

### Verify Phase 3

- [x] Round-trip:

  ```bash
  cd backend
  python -m app.services.llm "Reply with exactly the word 'pong'."
  ```

  Output contains `pong`.
- [x] Streaming works: add `--stream` to the same script; tokens print incrementally, not all at once.
- [x] Telemetry line: above run prints a log entry with the configured OpenRouter model id, non-zero `prompt_tokens`, `completion_tokens`, and `latency_ms`.
- [x] Retry on transient: temporarily set `OPENROUTER_BASE_URL` to a bogus host that 503s and run again — logs show retry attempts before final failure (then revert).

---

## Phase 4 — PDF ingest service

Goal: bytes in, clean text + metadata out.

- [x] **4.1 `services/pdf.py`**
  - `extract_text(file_bytes) -> ExtractedDoc{text, pages, char_count}`.
  - Try `pypdf`; if a page yields `< 30` chars, retry that page with `pdfplumber`.
  - Strip repeated headers/footers (lines that appear on `> 50%` of pages).
  - Acceptance: extracting `Documentation/Unleashing 10000 Word Generation From Long Context.pdf` yields plausible text (`> 20k` chars, page count matches).
- [x] **4.2 Hashing + dedupe helper**
  - `sha256(file_bytes)` returned alongside `ExtractedDoc`.
  - Acceptance: same file → same hash; different files differ.

### Verify Phase 4

- [x] Extraction:

  ```bash
  cd backend
  python -m app.services.pdf "../Documentation/Unleashing 10000 Word Generation From Long Context.pdf"
  ```

  Prints something like `pages=20 char_count=58231 sha256=…` and a sample of readable text (no garbled glyphs in the sample).
- [x] Hash stability: run the same command twice → identical `sha256`.
- [x] Hash uniqueness: run against `AI-Engineering-Assignment.pdf` → different `sha256`.
- [x] Header/footer stripping: the printed sample does not include the repeated paper title/page-number line that appears on every page.

---

## Phase 5 — LightRAG wiring

Goal: a singleton LightRAG instance using Supabase for KV+vectors, OpenRouter for LLM + embeddings.

- [x] **5.1 `services/rag.py` factory**
  - Build `LightRAG(working_dir=settings.LIGHTRAG_WORKING_DIR, llm_model_func=llm_model_func, embedding_func=openrouter_embed_func, kv_storage="PGKVStorage", vector_storage="PGVectorStorage")`.
  - `llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs)` adapts our `LlmClient.complete` to LightRAG's expected signature.
  - `openrouter_embed_func`: batched (`<= 64` inputs/call) using `get_async_openrouter_client().embeddings.create` with `OPENROUTER_EMBED_MODEL`, `embedding_dim` from the model (e.g. 1536 for `text-embedding-3-small`).
  - Init exactly once in FastAPI lifespan; expose via dependency.
  - Acceptance: server boots, `working_dir` gets created, no errors connecting to Supabase.
- [x] **5.2 `insert_document(text, doc_id)` wrapper**
  - Calls `rag.ainsert(text, ids=[doc_id])`.
  - Acceptance: small string can be inserted and a debug query returns context.
- [x] **5.3 `query(question, mode="hybrid", only_need_context=False)` wrapper**
  - Returns either the LLM answer or the raw context block.
  - Acceptance: querying a freshly-inserted snippet returns relevant context.

### Verify Phase 5

- [ ] Boot clean: start `uvicorn` → no LightRAG/asyncpg errors in the logs; `backend/.lightrag/` directory exists.
- [ ] Round-trip script — `backend/scripts/check_rag.py` (or inline equivalent). Use a **direct** Postgres URL (`db.*.supabase.co:5432`) via `SUPABASE_DB_URL` or `SUPABASE_DIRECT_DB_URL` (transaction pooler `:6543` breaks `pgvector` type registration). If TLS verification fails on your network, set `LIGHTRAG_PG_INSECURE_SSL=1` (dev only).

  ```bash
  cd backend
  python scripts/check_rag.py
  ```

  Output contains the word `Paris`.
- [ ] Supabase tables created: `psql "$SUPABASE_DB_URL" -c "\dt"` shows LightRAG's auto-created KV + vector tables in addition to `documents`.
- [ ] Singleton: run the script twice in quick succession from a Python REPL — second `get_rag()` returns the same instance (no re-init logs).

---

## Phase 6 — Upload + documents API

Goal: PDFs flow from frontend bytes into LightRAG and into the `documents` table.

- [x] **6.1 `POST /upload`**
  - Multipart endpoint, accepts 1+ files. For each: extract → hash → check `documents.sha256` → insert row → call `insert_document`.
  - Returns array of `{id, filename, pages, char_count, status: "ingested"|"duplicate"}`.
  - Acceptance: uploading the same PDF twice returns `duplicate` the second time and does **not** re-embed.
- [x] **6.2 `GET /documents`**
  - Lists rows from `documents` ordered by `created_at desc`.
  - Acceptance: matches what was uploaded.
- [x] **6.3 `DELETE /documents/{id}` (optional)**
  - Removes row + best-effort LightRAG delete (`rag.adelete_by_doc_id`).
  - Acceptance: list shrinks; subsequent queries don't surface that doc.

### Verify Phase 6

- [ ] First upload:

  ```bash
  curl -s -F "files=@Documentation/Unleashing 10000 Word Generation From Long Context.pdf" \
    localhost:8000/upload | jq
  ```

  Returns one entry with `status: "ingested"` and a UUID `id`.
- [ ] Dedupe: re-run the same command → same UUID, `status: "duplicate"`. Watch the logs: no embedding calls were made on the second run.
- [ ] List: `curl -s localhost:8000/documents | jq` shows exactly one row with the correct filename and page count.
- [ ] (Optional) Delete: `curl -s -X DELETE localhost:8000/documents/<id>` then re-list → row gone.

---

## Phase 7 — Chat endpoint

Goal: streaming, RAG-grounded answers.

- [x] **7.1 `POST /chat` (SSE)**
  - Body: `{message: str, history: [{role, content}]}`.
  - Steps: `context = rag.query(message, mode="hybrid", only_need_context=True)` → build system prompt that interpolates `context` and `history` → `llm.stream(...)` → yield `event: token` chunks → final `event: done`.
  - Honor `request.is_disconnected()`.
  - Acceptance: with one PDF uploaded, asking "Summarize the paper" streams a grounded answer.
- [x] **7.2 Handbook intent detection**
  - Helper `is_handbook_request(message) -> bool` (regex on `handbook|long-form|20[\s,]?000 words?|comprehensive guide`).
  - When true, chat replies with a short ack + a structured `event: redirect` containing `/handbook` payload, and the frontend opens the handbook flow.
  - Acceptance: "Create a handbook on RAG" triggers redirect, not a normal chat answer.

### Verify Phase 7

Prereq: the LongWriter PDF is uploaded (Phase 6 verification).

- [x] Streamed grounded answer:

  ```bash
  curl -N -X POST localhost:8000/chat \
    -H 'content-type: application/json' \
    -d '{"message":"Summarize the LongWriter / AgentWrite approach in 3 bullet points","history":[]}'
  ```

  You see multiple `event: token` lines arriving over a few seconds, then a final `event: done`. The concatenated text mentions `plan` and `write` (or `AgentWrite`).
- [ ] Disconnect honored: re-run the curl and `Ctrl+C` mid-stream → backend logs show "client disconnected" and no further LLM tokens are billed.
- [x] Handbook intent:

  ```bash
  curl -N -X POST localhost:8000/chat \
    -H 'content-type: application/json' \
    -d '{"message":"Please create a handbook on Retrieval-Augmented Generation","history":[]}'
  ```

  First non-token event is `event: redirect` with a JSON body pointing at `/handbook` and the topic.

---

## Phase 8 — AgentWrite service

Goal: faithful port of `LongWriter-main/agentwrite/` that uses the OpenRouter LLM and our LightRAG.

- [x] **8.1 Copy prompts verbatim**
  - `backend/app/services/prompts/plan.txt` ← `LongWriter-main/agentwrite/prompts/plan.txt`.
  - `backend/app/services/prompts/write.txt` ← `LongWriter-main/agentwrite/prompts/write.txt`, then append:

    ```
    Relevant context from uploaded PDFs (use it to ground the paragraph; cite document titles inline):

    $CONTEXT$
    ```

  - Acceptance: files exist and load via `importlib.resources` or relative path.
- [x] **8.2 `plan(instruction) -> list[Step]`**
  - Render `plan.txt` with `$INST$` = instruction. Append a hardening line: `Ensure the total word count across all paragraphs is at least 20,000 words and there are between 25 and 40 paragraphs.`
  - Call `llm.complete(max_tokens=4096)`, then parse lines matching `Paragraph N - Main Point: ... - Word Count: N words`.
  - Returns `Step{index, main_point, target_words, raw_line}`.
  - Acceptance: planning "Handbook on RAG" returns >= 25 well-formed steps totaling >= 20k target words. (The Phase 8.4 expansion pass closes any gap at the actual-output 20k floor.)
- [x] **8.3 `write_step(instruction, plan_text, written_text, step, context) -> str`**
  - Render `write.txt` with `$INST$`, `$PLAN$`, `$TEXT$`, `$STEP$`, `$CONTEXT$`. Call `llm.complete(max_tokens=4096)`.
  - Post-process: strip `Paragraph N`, `Main Point:`, `Word Count:`, leading bullets.
  - Acceptance: round-trips on a 3-step toy plan, output stays under target+30%.
- [x] **8.4 `generate_handbook(instruction, on_event)` orchestrator**
  - Flow: plan → emit `plan_ready` → loop steps serially:
    1. `context = rag.query(f"{instruction}\n{step.main_point}", mode="hybrid", only_need_context=True)`.
    2. `paragraph = write_step(...)`.
    3. emit `paragraph` event with `{index, total, text, words, running_total}`.
    4. append to `written_text`.
  - After loop: count words. If `< 20,000`, emit `expanding`, then iterate shortest paragraphs and call an `expand(paragraph, context)` LLM prompt that asks for more depth + additional citations until threshold reached or `total >= 30,000`.
  - Returns final markdown with auto-generated TOC from `Main Point` headings.
  - Acceptance: dry run on the provided PDFs produces `>= 20,000` words and TOC.
- [x] **8.5 Cancellation hook**
  - `on_event` callback returns `False` if client disconnected; orchestrator stops cleanly.
  - Acceptance: closing the browser tab stops LLM calls within one paragraph.

### Verify Phase 8

- [x] Prompt parity: `diff backend/app/services/prompts/plan.txt LongWriter-main/agentwrite/prompts/plan.txt` is empty. The same `diff` for `write.txt` shows **only** the appended `$CONTEXT$` block.
- [x] Plan call:

  ```bash
  cd backend
  python -m app.services.agentwrite plan "Handbook on Retrieval-Augmented Generation"
  ```

  Prints between 25 and 40 lines, every line matches `Paragraph N - Main Point: ... - Word Count: N words`, and the sum of `Word Count` numbers is `>= 20000`.
- [x] Single write step:

  ```bash
  python -m app.services.agentwrite write-step \
    --instruction "Handbook on RAG" \
    --plan-line "Paragraph 1 - Main Point: Define RAG and motivate its existence - Word Count: 600 words"
  ```

  Output is a single paragraph of roughly 450–800 words, with no leading `Paragraph 1` / `Main Point:` / bullet markers.
- [x] Full dry run (expensive — only when 8.4 is in):

  ```bash
  python -m app.services.agentwrite generate "Handbook on RAG" > /tmp/handbook.md
  wc -w /tmp/handbook.md
  ```

  Word count `>= 20000`. Top of file contains a `## Table of Contents` section. Headings include the `Main Point` text from the plan.
- [ ] Cancellation: rerun `generate` and `Ctrl+C` after the first `paragraph` event → process exits within one extra paragraph; logs show no further LLM calls after the cancel.

---

## Phase 9 — Handbook endpoint

Goal: expose the orchestrator over SSE.

- [ ] **9.1 `POST /handbook` (SSE)**
  - Body: `{topic: str, document_ids?: str[]}` (filter retrieval if provided).
  - Streams events from Phase 8.4. Persists final markdown to `backend/.handbooks/{uuid}.md` and stores a row in `handbooks` table (`id, topic, words, created_at, path`).
  - Acceptance: end-to-end SSE delivers `plan_ready` → many `paragraph` events → `done` with final markdown.
- [ ] **9.2 `GET /handbook/{id}` + `GET /handbook/{id}/download?format=md|pdf`**
  - Markdown read from disk; PDF rendered with `weasyprint` or `markdown-pdf` (pick one and pin).
  - Acceptance: both formats download correctly and word count holds.

### Verify Phase 9

- [ ] Stream:

  ```bash
  curl -N -X POST localhost:8000/handbook \
    -H 'content-type: application/json' \
    -d '{"topic":"Handbook on Retrieval-Augmented Generation"}' | tee /tmp/handbook.sse
  ```

  You see one `event: plan_ready`, many `event: paragraph` (with monotonically increasing `index` and `running_total`), optionally `event: expanding`, and finally one `event: done` with `{id, words}` where `words >= 20000`.
- [ ] Persisted: `psql "$SUPABASE_DB_URL" -c "select id, topic, words from handbooks order by created_at desc limit 1"` shows the row; `ls backend/.handbooks/` contains the matching `.md` file.
- [ ] Markdown download:

  ```bash
  ID=<id-from-done-event>
  curl -s "localhost:8000/handbook/$ID/download?format=md" -o /tmp/h.md
  wc -w /tmp/h.md   # >= 20000
  head -n 20 /tmp/h.md   # shows TOC + first heading
  ```

- [ ] PDF download:

  ```bash
  curl -s "localhost:8000/handbook/$ID/download?format=pdf" -o /tmp/h.pdf
  file /tmp/h.pdf   # reports "PDF document"
  ```

---

## Phase 10 — Frontend: documents

Goal: drag-drop upload + list.

- [x] **10.1 `Uploader.tsx`** — drag-drop + click-to-select, posts multipart to `/upload`, shows per-file progress and result.
- [x] **10.2 `DocumentList.tsx`** — polls `/documents`, shows filename, pages, ingested-at, delete button.
- [x] **10.3 Wire into `App.tsx` left rail.**
- Acceptance: uploading 1–3 PDFs surfaces them in the list, duplicates are flagged.

### Verify Phase 10

- [ ] Drag-drop a PDF onto the left rail → progress bar appears, then the file shows up in the list with correct page count.
- [ ] Drop the same PDF again → list does not duplicate; UI surfaces a "duplicate" indicator (toast, badge, or row state).
- [ ] Hard-refresh the browser → list is still populated (data came from `/documents`, not local state).
- [ ] (If 6.3 implemented) Delete button removes the row from the UI and from `GET /documents`.

---

## Phase 11 — Frontend: chat

Goal: streaming chat with grounded answers.

- [x] **11.1 `Chat.tsx`** — message list (markdown-rendered assistant), input box, send-on-enter, history kept in component state.
- [x] **11.2 SSE consumer** — `openSse('/chat', body, {token, done, redirect, error})` updates the in-flight assistant message token-by-token.
- [x] **11.3 Redirect to handbook** — on `redirect` event, switch to the Handbook panel pre-filled with the topic.
- Acceptance: ask a factual question about an uploaded PDF, get a grounded streamed answer; ask for a handbook, get redirected.

### Verify Phase 11

- [ ] Type "Summarize the LongWriter approach" → assistant bubble fills in token-by-token (visible streaming, not one-shot), final markdown is rendered (lists/bold formatted, not raw `**`).
- [ ] Multi-turn: send a follow-up "What does AgentWrite mean by 'serial'?" → backend receives the previous turn in `history`; response is coherent with the prior turn.
- [ ] Redirect: type "Create a handbook on RAG" → focus jumps to the Handbook panel, topic field is pre-filled with "Handbook on RAG" (or the user's exact phrasing).
- [ ] Error path: stop the backend, send a chat message → an inline error message appears (no silent failure, no spinner stuck forever).

---

## Phase 12 — Frontend: handbook

Goal: live progress + final document.

- [x] **12.1 `HandbookView.tsx`** — topic input, Generate button, progress bar (`paragraphs done / total planned`, running word count), live markdown preview that grows as paragraphs arrive.
- [x] **12.2 Cancel button** — closes the `EventSource`, server drops the run.
- [x] **12.3 Download buttons** — `.md` and `.pdf` via `/handbook/{id}/download`.
- Acceptance: full run for "Handbook on RAG" with the assignment PDFs streams to completion, preview shows TOC + headings, downloads work.

### Verify Phase 12

- [ ] Click Generate with topic "Handbook on RAG" → progress bar advances as paragraphs arrive; word counter ticks up past 20,000 before the run ends; preview pane scrolls with new content.
- [ ] Cancel: start a fresh run, click Cancel after a few paragraphs → backend logs show "handbook run cancelled" and LLM calls stop within one paragraph.
- [ ] Download `.md` → file opens in your editor, top contains TOC, `wc -w` of the file is `>= 20000`.
- [ ] Download `.pdf` → opens in a PDF viewer, headings and TOC render, content matches the markdown.

---

## Phase 13 — End-to-end testing

- [ ] **13.1 Smoke script** — `backend/scripts/e2e.py` that uploads the LongWriter PDF, runs a chat query, runs a handbook generation, asserts `>= 20k` words.
- [ ] **13.2 Manual run of the README test case** — upload 2–3 AI PDFs, chat, generate handbook on RAG, confirm TOC + citations + word count.
- [ ] **13.3 Capture demo** — screen recording (or 5+ screenshots) into `docs/demo/`.

### Verify Phase 13

- [ ] `python backend/scripts/e2e.py` exits 0 on a fresh database (drops + re-runs schema, uploads, chats, generates, asserts). The script prints final word count and handbook id at the end.
- [ ] Manual run captured: `docs/demo/` contains either `demo.mp4`/`demo.mov` or at least 5 screenshots covering: empty state, after upload, chat answer, handbook progress mid-run, finished handbook with downloads visible.
- [ ] Final handbook from the manual run is committed to `docs/demo/sample-handbook.md` so reviewers can read the artifact without running the app.

---

## Phase 14 — Documentation & submission

- [ ] **14.1 `docs/writeup.md`** — what was built, architecture diagram (reuse from `AGENTS.md`), AgentWrite adaptation notes, challenges, what we'd do with more time.
- [ ] **14.2 Update top-level `README.md`** — keep the assignment text, add a "How to run this submission" section linking to `AGENTS.md` §5.
- [ ] **14.3 Final checklist sweep** — every box in `README.md` "Submission Checklist" is ticked.
- [ ] **14.4 Tag submission commit** (only when user requests).

### Verify Phase 14

- [ ] Cold-clone test: in a temp directory, `git clone <repo>` (or unzip), follow the `README.md` setup section verbatim, end up with a working app that can run the README test case. Note any step the docs missed and fix them.
- [ ] Every checkbox under "Submission Checklist" in `README.md` is ticked.
- [ ] `docs/writeup.md` reads cleanly end-to-end (no TODOs left).
- [ ] All Phase 0–13 Verify blocks in this file are fully ticked.

---

## Stretch (only if time permits)

- [ ] Per-user sessions (currently single-tenant).
- [ ] Background job queue (Celery / RQ) so handbook runs survive page reloads.
- [ ] Caching plan + write step responses by `(instruction, plan, step)` hash to cut re-run cost.
- [ ] Inline citation links in the handbook back to PDF page numbers (LightRAG returns chunk ids; map to source pages).
- [ ] Auth (Supabase Auth) for multi-user demo.

---

## Status legend

- `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (note why)

Update this file in the same change that completes a task.
