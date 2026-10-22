# CDIS — Career Decision Intelligence System

> **Proof, not pitch.** AI just made every career claim infinitely cheap to fabricate — exactly as real work (repos, deployments, shipped projects) became machine-verifiable. CDIS scores what you can *actually* do, and refuses to invent a single number.

Paste your résumé and in seconds you get an evidence-scored profile that's honest to a fault — **high where you've shipped, brutally low where you've only claimed** — with every score traceable to the artifact behind it. No "92% match." No "chance of getting hired." Every recommendation carries its evidence, its confidence, and a reasoning trace you can **replay byte-for-byte**. Turn the AI off entirely and the product still works.

**What's genuinely different**

- **Verified, not claimed.** Skills score from real evidence — repos, deployments, shipped work. A certificate alone is capped at Medium (40/100). Every cell shows its receipts.
- **No fabricated numbers.** A deterministic rule engine produces every score; the language model only rephrases explanation text, behind a grounding check that rejects any invented figure. If the model disappears, every feature still works.
- **Every decision is replayable.** Inputs, evidence, and engine version are stored and recomputed to prove the result reproduces — the trust feature, the debugger, and the demo centerpiece in one.

This is the runnable MVP of the [CDIS Reference Architecture v2.0](docs/ARCHITECTURE.md) — the §12 vertical slice, end-to-end: SPA + landing page, auth, event-sourced Career Twin, Evidence Scorecard, gap analysis, human-approved résumé versioning, decision audit + replay, mission health, and a live graceful-degradation kill switch. One command, no build step, 32 tests.

---

## Quickstart

**Local (zero configuration — SQLite):**

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# http://127.0.0.1:8000            app (SPA)
# http://127.0.0.1:8000/landing    marketing page
# http://127.0.0.1:8000/api/docs   OpenAPI (dev only; disabled when APP_ENV=production)
```

**Docker:**

```bash
docker compose up --build            # SQLite volume
docker compose --profile postgres up # + Postgres (set DATABASE_URL in .env)
```

**Tests + lint:**

```bash
pip install -r requirements-dev.txt
ruff check app tests && pytest       # 32 tests: invariants, security, privacy
```

Configuration is documented in [`.env.example`](.env.example). Set `JWT_SECRET` in production.

---

## What it does (the 4-minute demo)

1. **Ingest** — paste a resume. The parser chain (structured sections → lexicon heuristics → manual input) extracts facts with per-field confidence. ≥0.80 auto-accepts; 0.60–0.79 waits in your confirm queue; quantified claims ("reduced latency by 40%") always require manual verification. Unverified facts never enter reasoning.
2. **Evidence Scorecard** — every accepted skill is scored from verified evidence (repo +30, deployment +25, project +20 … certificate +10). **Invariant: certificates alone are capped at 40/100 (Medium).** Every score cell shows the exact items and rule behind it.
3. **Gap analysis** — paste a job description. Output: Alignment Score 0–100, ranked limiting factors with mention counts and estimated gains, one highest-leverage Career Investment, confidence + basis, and a disclaimer. **There is no hiring-probability field anywhere in the API contract — by design and by test.**
4. **Resume studio** — a draft built *only* from accepted facts, reordered for the target role, shown as a diff. Nothing is saved until you approve; approved versions are immutable with parent links (git-like history).
5. **Decision replay** — click any decision in the audit log: inputs, twin hash, evidence used, engine version, fallback flag — and a deterministic recomputation proving the result reproduces.
6. **Kill switch** — flip "simulate LLM outage" in the mission strip and run another analysis. The rule engine answers, the fallback is honestly labeled, counters tick up. *Quality may degrade; the mission does not.*

## Evidence-based AI, concretely

All numbers come from a deterministic, inspectable rule engine over the accepted Twin and the pasted JD — a language model **cannot** fabricate them because it never produces them. The optional LLM adapter (set `ANTHROPIC_API_KEY`) only rephrases explanation text, behind a fixed system prompt, and every rewrite passes a **grounding check**: if it invents or alters any number it is rejected and the deterministic template is used (`fallback_used`). Verified rewrites are cached per template so identical analyses never re-call the model. Every gap-analysis response carries the full trio — evidence, confidence, explanation. If the LLM layer disappears entirely, every feature still works.

## Architecture

```
Browser SPA (static, no build step)
   │  JWT
   ▼
FastAPI ── ObservabilityMiddleware (trace id, latency, tiered rate limit, CSP + security headers)
   ├── /api/auth        register/login (PBKDF2 + JWT, constant-time, throttled)
   ├── /api/twin        event-sourced Career Twin, HITL facts, evidence, scorecard
   ├── /api/decisions   gap analysis (rule engine primary, LLM cosmetic + grounded)
   ├── /api/resume      draft → diff → human approve → immutable versions
   ├── /api/audit       decision log + deterministic replay
   ├── /api/account     data export + password-confirmed hard delete
   └── /api/health      liveness + mission health + (admin) kill switch
        │
   SQLAlchemy ── SQLite (default) / Postgres (DATABASE_URL)
```

Design properties carried from the blueprint: append-only event sourcing (versioning, rollback, timeline, and replay from one mechanism); twin content hash on accepted facts only; HITL confidence tiers; no single opaque confidence number (extraction confidence ≠ evidence scorecard ≠ recommendation confidence); parser fallback chain with a manual terminal; per-request trace IDs and latency headers; per-IP token-bucket rate limiting; non-root Docker with healthcheck; CI running lint + tests + image build.

## API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` · `/api/auth/login` | JWT auth |
| POST | `/api/twin/resume` · `/api/twin/resume/file` | Ingest via parser chain |
| GET | `/api/twin` | Projected Twin + pending HITL queue |
| POST | `/api/twin/facts` | Manual fact (terminal parser fallback) |
| POST | `/api/twin/facts/{id}/confirm` · `/reject` | HITL resolution (events, nothing deleted) |
| POST | `/api/twin/evidence` | Attach evidence to an accepted skill |
| GET | `/api/twin/scorecard` | Evidence Scorecard with rules + citations |
| POST | `/api/decisions/gap-analysis` | Alignment, limiting factors, investment |
| POST | `/api/resume/draft` · `/approve` | Draft+diff, then human-approved version |
| GET | `/api/resume/versions` | Immutable history |
| GET/POST | `/api/audit` · `/api/audit/{id}` · `/api/audit/{id}/replay` | Decision audit + replay |
| GET/POST | `/api/account/export` · `/api/account/delete` | Data portability · password-confirmed erasure |
| GET | `/api/health` · `/api/health/mission` | Liveness · component health + fallback counters |
| POST | `/api/admin/llm-kill-switch` | Graceful-degradation demo (**admin only**) |

## Security & privacy

Production-reviewed: JWT auth fails fast if `JWT_SECRET` is unset in production; login is constant-time (no user-enumeration timing oracle) and `/api/auth/*` is rate-limited tighter than the general API to blunt brute force. Every response carries a Content-Security-Policy plus `X-Frame-Options`/`nosniff` (HSTS in production); interactive docs are disabled in production. Cross-user access returns `404`, not `403` (no existence oracle); the kill switch is admin-only. The LLM only ever sees structured evidence behind a system prompt, and its output is grounding-checked. Users own their data: `/api/account/export` (portability) and `/api/account/delete` (password-confirmed hard delete). No PII or secrets in logs.

## Honest limitations (stated, not hidden)

- **Skill extraction is lexicon-based** (~40 curated skills). Deliberate for the MVP: inspectable, deterministic, zero hallucination. Extending the lexicon is a one-line change; swapping in an ML extractor slots behind the same `ExtractedFact` interface.
- **Rate limiting and fallback counters are per-process.** Multi-instance production moves them to Redis; interfaces are unchanged.
- **GitHub evidence is now auto-fetched.** `POST /api/twin/evidence/github {username}` pulls public repos, maps them to skills, and builds the scorecard from *verified* work (set `GITHUB_TOKEN` for higher rate limits). Manual attach remains for anything off-GitHub.
- **Alignment starts brutally low for unevidenced profiles.** That's the product working: claims without evidence don't count. Attach a repo and watch the needle move — that's the demo moment.
- **Outcome tracking is live** (`/api/outcomes`): consented applied → interview → offer funnel, linked to the decision that preceded it — the evidence→outcome corpus and the measurable North Star. Calibrating scores on this data is the next AI milestone (needs volume).

## Roadmap to the full blueprint

MVP (this repo) → GitHub MCP evidence fetch → outcome tracking + North Star instrumentation → GraphRAG knowledge service → event bus + async workers → the full 8-service target state. Every component here is a strict subset of the target architecture; nothing gets thrown away.

## License

MIT © 2026 Jwalith Madhyahnapu
