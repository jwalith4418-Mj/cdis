# CDIS — Engineering Review (resolved)

This records the production hardening applied on top of the [v2.0 blueprint](ARCHITECTURE.md).
Every item below is **implemented and covered by tests** (`pytest` — 32 tests). It is a
statement of the current state, not a backlog.

## Correctness
- Evidence linking uses whole-token matching, not substrings, so a "Digital Marketing" certificate cannot attach to the skill **Git**.
- One `compute_alignment` core is shared by gap analysis and replay, so replay reproducibility is structural rather than a second implementation kept in sync.
- Resume versioning is protected by a `UNIQUE(user_id, version)` constraint with retry — no lost-update races.
- The fact state machine forbids resurrecting a rejected fact.

## Architecture & coupling
- JD parsing lives in `parser.py` next to the lexicon it uses; the Decision, Resume, and Audit engines depend on the parser, not on each other. `resume.py` has no dependency on `decision.py`.
- No cross-module imports of private (`_`-prefixed) helpers.
- Single FastAPI monolith on deliberately boring tech — no premature microservices.

## Security
- JWT fails fast if `JWT_SECRET` is unset in production; HS256 with explicit algorithm (no `alg=none`).
- Constant-time login (dummy PBKDF2 on unknown email) — no timing-based user enumeration; identical error for both cases.
- Tiered rate limiting: `/api/auth/*` throttled tighter than the general API; bounded bucket map; `Retry-After`; proxy-aware client IP.
- Object-level authz: cross-user access returns `404`; the kill switch is admin-only.
- Content-Security-Policy, `X-Frame-Options`, `nosniff`, `Referrer-Policy` on every response; HSTS in production; interactive docs disabled in production.
- File uploads are size-capped; the LLM sees only structured evidence behind a system prompt and its output is grounding-checked; no PII or secrets in logs.

## Privacy
- `/api/account/export` (data portability) and `/api/account/delete` (password-confirmed hard delete cascading events, decisions, and versions).

## Performance
- Lexicon alias patterns precompiled once at import (identical output; `extract_jd_requirements` ~20% faster, no redundant pass).
- Twin projection cached per user, keyed on the latest event id; the cache returns the projection without a per-request `deepcopy` (~40% faster `project()`), treated read-only by callers.
- `pool_pre_ping` recycles dropped DB connections. Measured p50: `GET /api/twin` ~3.7 ms, gap analysis ~5 ms.

## Reliability & observability
- Graceful degradation everywhere: LLM → deterministic rule engine; real per-component health probes; structured JSON logs with a request-scoped `trace_id`; consistent `{detail, trace_id}` error envelope.

## Known boundaries (by design, documented)
- In-process rate-limit/cache/counter state is per-process; Redis is the noted multi-instance path.
- Schema is created with `create_all` (no migrations yet); GitHub evidence fetch and outcome tracking are the next milestones. See the README's roadmap.
