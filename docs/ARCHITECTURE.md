# Career Decision Intelligence System (CDIS)
## Reference Architecture v2.0 — Final Consolidated Blueprint

**Doctrine:** Mission First · Trust First · KISS · Design for Success · Refined to Avoid Failure
**Governing NFR:** No user ever waits for work that can be done asynchronously.
**Status:** Supersedes v1.0 and all intermediate advisory drafts. All contradictions between prior drafts are resolved here. This document is the single source of truth for the system design.

---

## 0. Mission, North Star, and Scope

**Mission.** Help users make better career decisions through explainable, evidence-based intelligence that continuously adapts to their goals and verified achievements.

**Product category (honest positioning).** CDIS is an AI Career Platform by category — the category is not novel. The differentiation is integration quality plus trust architecture: a longitudinal Career Twin, verified evidence, explainable decisions, and outcome-driven learning. That combination is the moat; no single technology is.

**North Star Metric.** Verified Outcome Progression Rate: the fraction of active users who, within a rolling 90-day window, advance at least one stage in the funnel `Application → Interview → Offer` on a target-role application, with the contributing recommendations traceable in the Decision Audit log. Vanity metrics (resumes generated, ATS scores, courses completed) are explicitly excluded from success criteria.

**Prohibited claims (product-wide invariant).** The system never displays a "chance of getting hired" or any probability of an offer. All readiness output is an **Alignment Score (0–100)** with named limiting factors, supporting evidence, and estimated improvement potential. Enforced at the API contract level: the Decision Engine response schema has no `hiring_probability` field.

**Scope discipline.** Two scopes are defined and never conflated:

| Scope | Definition |
|---|---|
| **MVP (hackathon)** | One polished vertical slice (§12): ingest → Career Twin → evidence scoring → gap analysis → one company-adapted resume with diff + human approval → decision replay. |
| **Target state** | The full 8-service platform in this document. Every MVP component is a strict subset of the target state — no throwaway code, no redesign required to scale. |

**Load target.** Designed for 2,500 **concurrent** users (not 2,500 total). This is the binding constraint behind the caching, queueing, and incremental-computation decisions in §8.

---

## 1. The Five-Gate Feature Filter (CTO Decision Filter)

Every feature, present and future, must pass all five gates or it is removed:

1. Why does this exist?
2. What measurable problem does it solve?
3. How do we know it works?
4. What happens if it fails?
5. Can it be explained to a judge or CTO in under 60 seconds?

**Removed by this filter (final, non-negotiable):** auto-apply to jobs; silent AI resume edits; single opaque confidence numbers as user-facing skill ratings; hiring-probability percentages; AI cover-letter generator as a headline feature; "an agent for everything"; 25-microservice decomposition; multiple AI models redundantly solving the same problem; any dependency on unrestricted LinkedIn/job-board API access.

---

## 2. High-Level Architecture — Eight Platform Services

Resolution of prior drafts: the "5 engines," "6 bounded contexts," and "7 platforms" from intermediate iterations are **conceptual views**. The **deployable architecture is exactly eight services**. The five conceptual engines (Career Twin, Career Intelligence, Decision, Execution, Outcome) map onto them as noted. Cross-cutting concerns (§7) are shared libraries and infrastructure, not services.

```text
                 ┌──────────────────────────────┐
                 │      Experience Layer         │
                 │  Web SPA · Mobile · (later:   │
                 │  Recruiter Portal)            │
                 │  UI only — zero AI logic      │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │      1. API Gateway           │
                 │ AuthN/AuthZ · Rate limit ·    │
                 │ Validation · Cache · Trace ID │
                 └──────────────┬───────────────┘
                                │
                 ┌──────────────▼───────────────┐
                 │   Mission Controller          │
                 │ (library inside Gateway tier, │
                 │  not a separate network hop)  │
                 │ Mission routing · cache check │
                 │ · fallback selection · retry  │
                 └──┬──────┬──────┬──────┬──────┘
                    │      │      │      │
     ┌──────────────▼┐ ┌───▼────┐ ┌▼─────────┐ ┌▼──────────┐
     │ 2. Career Twin│ │3. Know-│ │4. Decision│ │5. Resume  │
     │    Service    │ │ ledge  │ │  Engine   │ │  Engine   │
     │ (SoT + Evi-   │ │Service │ │ (AI brain)│ │(gen+diff) │
     │  dence Engine)│ │RAG +   │ └───────────┘ └───────────┘
     └───────────────┘ │GraphRAG│
                       └────────┘
     ┌───────────────┐ ┌──────────────────┐ ┌───────────────┐
     │ 6. Integration│ │7. Mission        │ │ 8. Event Bus  │
     │  Service (MCP)│ │  Assurance       │ │ + Queue        │
     │ GitHub·Jobs·  │ │ Health·Fallback· │ │ async work ·   │
     │ Email·Storage │ │ Recovery·Audit   │ │ notifications  │
     └───────────────┘ └──────────────────┘ └───────────────┘
```

| # | Service | Single Responsibility | Conceptual engines hosted | Scales independently |
|---|---|---|---|---|
| 1 | API Gateway + Mission Controller | Entry, auth, rate limit, validation, cache check, mission routing, fallback selection | — | ✅ |
| 2 | Career Twin Service | Source of truth for user state; versioning; **Evidence Engine** (verification + scoring) | Career Twin, Evidence Intelligence, Outcome Engine (write side) | ✅ |
| 3 | Knowledge Service | Static RAG + dynamic GraphRAG retrieval; Market/Company graphs | Market Intelligence | ✅ |
| 4 | Decision Engine | All AI reasoning: gap analysis, alignment, learning ROI, interview prep, opportunity ranking | Decision Intelligence, Career Intelligence | ✅ |
| 5 | Resume Engine | Resume generation, company adaptation, diff, export; never mutates without approval | Career Execution (documents) | ✅ |
| 6 | Integration Service (MCP) | External connections only — GitHub, learning platforms, job APIs, email, calendar, storage, auth providers. Zero business logic. | — | ✅ |
| 7 | Mission Assurance | Health aggregation, fallback policy, recovery orchestration, incident + decision audit store | — | ✅ |
| 8 | Event Bus + Queue | Async messaging, background jobs, notification dispatch (Notification is a consumer, not a service) | — | ✅ |

**Merges made (with rationale):** Evidence Engine merged into Career Twin Service — evidence is an attribute of Twin facts and shares its transactional boundary; a network hop between "fact" and "its proof" invites inconsistency. Notification Platform demoted to an Event Bus consumer — it is a delivery channel, not a domain. Human Decision Platform is not a service; human checkpoints are a UI pattern + workflow state in whichever service owns the pending change (§6). Learning, Interview, and Opportunity "platforms" are **modules inside the Decision Engine** sharing one retrieval context — separating them duplicated context assembly, the most expensive operation in the system.

---

## 3. Career Twin Service — Single Source of Truth

Everything reads from the Twin. Everything writes back through the Twin. No other service persists user career facts.

### 3.1 Data model

```text
CareerTwin (versioned, append-only event log + current-state projection)
├── Identity              (name, contacts, links)
├── Education[]
├── Experience[]
├── Projects[]            → each links to Evidence[]
├── Skills[]              → each carries an EvidenceScorecard entry
├── Certifications[]      → never raise confidence alone (invariant, §5)
├── Evidence[]            (source, artifact URI, verification status, verified_at)
├── CareerGoals[]         (target roles/companies, horizon)
├── ResumeVersions[]      (immutable; diff-linked; git-like DAG)
├── Applications[]        (status: draft→applied→interview→offer/rejected)
├── InterviewHistory[]
├── LearningProgress[]    (investment → artifact required → verified?)
├── Outcomes[]            (user-consented results; feeds Learning Loop)
└── CareerTimeline        (derived projection, not stored duplicated)
```

### 3.2 Rules

- **Append-only event sourcing.** No fact is overwritten; the current state is a projection. This gives version control, rollback, decision replay, and the Career Timeline for free — one mechanism, four features (KISS).
- **Every write is an event** on the Event Bus: `certificate.uploaded → twin.updated → resume.suggestion.created → dashboard.updated → notification.sent`. No service calls another directly for propagation.
- **Twin hash.** Each Twin version has a content hash; all caches (§8) key on it. Unchanged Twin ⇒ zero recomputation.
- **Ownership & consent.** Outcomes (offers, rejections) are recorded only with explicit user consent, are deletable, and are excluded from any cross-user analytics unless separately consented (§10).

### 3.3 The "AI removed" test (passed)

If every LLM disappears tomorrow, the product still provides: Career Twin state, resume version control with diff/rollback, application tracker, interview tracker, learning planner with evidence checklist, evidence repository, career timeline. AI is an accelerator layered on a durable system of record — the foundation is not the model.

---

## 4. Knowledge Service — Static RAG, Dynamic GraphRAG, Never Mixed

| Store | Technology role | Contents | Update cadence |
|---|---|---|---|
| **Static Knowledge (RAG)** | Vector index over curated corpus | Resume/ATS guidelines, interview frameworks, learning resources, career frameworks, public company info, salary insights (public sources), industry trends | Editorial, weekly |
| **Dynamic Knowledge (GraphRAG)** | Property graph per user + shared market graph | Skill Graph, Project Graph, Evidence Graph, Career Graph, Learning Dependency Graph, Job Requirement Graph, Company Graph | Event-driven, on Twin change |

**Justification (failure-mode framing, not fashion):** RAG prevents ungrounded advice — every guideline the Decision Engine cites resolves to a trusted document. GraphRAG exists because career reasoning is multi-hop relational ("which single missing competency blocks the most target roles?", "which existing project already demonstrates three required skills?") — flat retrieval fails these queries. GraphRAG is used **only** for relationship reasoning; anything answerable by static retrieval stays in RAG (cheaper, faster, simpler).

**Data-availability constraint (resolved risk).** The architecture assumes **no** unrestricted access to LinkedIn or scraped job boards. Job requirements enter via: (a) user-pasted job descriptions (primary, always works), (b) licensed/partner job APIs through the Integration Service (enhancement), (c) curated public company information (enhancement). Enhancements degrade gracefully to path (a).

**Retrieval fallback chain:** GraphRAG → vector search → keyword search → cached knowledge → answer with reduced-context disclosure. Quality degrades; the mission does not.

---

## 5. Evidence Model — Scorecard, Not a Number

**Resolution of the confidence contradiction in prior drafts:** there are **three distinct confidence types**, and only one of them is a single number. Conflating them was the root inconsistency; it is now split:

| Type | Applies to | Form | Consumer |
|---|---|---|---|
| **Extraction confidence** | Each parsed field (e.g., "reduced latency by 40%") | Per-field 0–1 score | HITL policy (§6) — decides auto-accept vs. ask user |
| **Evidence Scorecard** | Each skill/competency dimension | Score + enumerated evidence items | User-facing profile; Decision Engine input |
| **Recommendation confidence** | Each Decision Engine output | High/Medium/Low + evidence citations | Displayed with every recommendation |

### 5.1 Evidence Scorecard (user-facing skill model)

```text
Dimension              Score   Evidence
Technical Skills         84    6 verified projects (repo links)
Backend Engineering      71    2 production-quality projects
Cloud Deployment         38    no deployed cloud artifact
Communication            67    technical blog + recorded presentation
Open Source              15    no accepted contributions
```

Scoring inputs: GitHub (repos, commit history via MCP), deployed artifacts, portfolio entries, certificates, hackathon results, blogs/publications, manual verification. **Invariant: a certificate alone never raises a skill above Medium evidence.** Certificate + built artifact + deployment = High. Every score cell is clickable → shows the exact evidence items and the scoring rule applied. No black boxes.

### 5.2 Readiness output (replaces all probability language)

```text
Target: Google SWE Internship
Overall Alignment: 72 / 100          Evidence strength: High
Limiting factors (ranked by impact):
  1. Cloud deployment  — no verified artifact   (est. +6 alignment)
  2. Open source       — no accepted PRs        (est. +3)
  3. Distributed systems — course only, no build (est. +2)
Estimated improvement potential: +11 alignment points
Basis: N matching job descriptions analyzed · model vX · replayable (Decision ID)
```

Every number traces to evidence; every estimate is labeled an estimate; every output is replayable (§7.2).

---

## 6. Human-in-the-Loop — Confidence-Tiered Action Policy

AI recommends; humans own important decisions. The tier policy applies to **extraction confidence and automation decisions** (not to skill scorecards, which are always shown in full):

| Extraction/automation confidence | System action |
|---|---|
| > 95% | Auto-draft; surfaced in review queue, applied on user acceptance |
| 80–95% | Shown as suggestion with evidence; one-tap accept/reject/edit |
| 60–80% | Explicit user confirmation required before entering the Twin |
| < 60% | Manual verification required; fact excluded from reasoning until verified |

**Hard human checkpoints (regardless of confidence):** resume modifications (via Diff Engine: AI draft → diff view → accept/reject/edit per hunk → new immutable version), career-goal changes, evidence verification status changes, resume export, application submission (**user always clicks Apply — the system prepares a readiness checklist, never applies**), and account/data deletions. AI never performs irreversible actions.

Every human decision (accept/reject/edit) is itself an event → stored in the Decision Audit → feeds the Learning Loop. The human is inside the intelligence loop, not a speed bump on it.

---

## 7. Mission Assurance Service

### 7.1 Health, fallback, recovery

Every service publishes `Healthy | Warning (slow/degraded) | Unavailable` plus latency and error rate. Mission Controller consumes the aggregate **Mission Health Score** and selects Primary → Fallback → Recovery per request. Standard fallback chains (all implemented, all tested with fault injection):

```text
Resume parsing : Parser A → Parser B → OCR → LLM structured extraction
                 (each stage emits per-field extraction confidence) → manual input
LLM inference  : primary model → retry w/ backoff → fallback model
                 → rule engine (deterministic checks: keywords, formatting,
                   metrics presence) → cached prior result → honest degradation notice
Retrieval      : GraphRAG → vector → keyword → cached knowledge
GitHub (MCP)   : live → cached snapshot → skip card, continue mission, retry bg
Learning APIs  : live → cached learning graph → offline curated database
Database       : primary → read replica → write queue → restore → replay queue (zero lost writes)
Resume Engine  : generate → on failure: previous version + verified incremental changes, retry bg
Decision Engine: fresh reasoning → last successful roadmap + staleness notice
```

Self-healing loop: `Failure → Detect → Diagnose → Select recovery → Execute → Validate → Log incident → Update runbook/knowledge base` — failures make future recovery faster (Failure Flywheel).

### 7.2 Decision Audit + Decision Replay

Every AI decision persists: `{decision_id, input Twin hash, evidence items used, retrieval trace, model + version, prompt/template version, confidence, fallback used?, human action, outcome (when known), timestamp}`. **Decision Replay** reconstructs the exact reasoning path for any recommendation ("Why did you tell me to learn Docker?" → the 15 job descriptions, the gap, the ROI computation, the model version). This is the trust feature, the debugging tool, and the demo centerpiece — one mechanism, three payoffs.

### 7.3 FMEA (consolidated, all prior drafts merged)

| Failure | Likelihood | Impact | Detection | Mitigation | Residual |
|---|---|---|---|---|---|
| PDF parse failure | H | Critical | per-stage confidence | 4-stage parser chain + paste/DOCX/manual builder | Acceptable |
| LLM API outage | M | H | timeout/error rate | retry → fallback model → rule engine → cache | Degraded quality, mission continues |
| Graph DB down | L | M | health probe | vector → keyword → cache | Acceptable |
| GitHub rate limit (429) | H | L | response code | cached snapshot; background refresh | Acceptable |
| Job API restricted/revoked | H | M | contract tests | user-pasted JDs are the primary path by design | Acceptable |
| DB primary crash | L | Critical | health probe | replica reads + queued writes + replay | Zero data loss target |
| Auth outage | L | H | probe | read-only guest analysis mode; no writes | Acceptable |
| Cold start (sparse user) | H | M | onboarding telemetry | resume-only value path: quality analysis + ATS check + evidence checklist in first session, <30s | Acceptable |
| Hallucinated recommendation | M | H (trust) | evidence-citation requirement | structured-evidence-only prompting; outputs lacking citations are rejected pre-display | Monitored via audit |
| Recommendation doesn't improve outcomes | M | Critical (existential) | North Star cohort tracking | Validation plan §11 | Open until data exists — stated honestly |

---

## 8. Performance Architecture — Latency by Design

**Anti-pattern eliminated:** `User → LLM → LLM → LLM → response`. Replaced by: structured Twin → incremental updates → reuse → AI only when necessary.

- **Cache (keyed on content hashes):** resume parses, GitHub analyses, JD parses, learning graph, company analyses, Twin snapshots. Never recompute unchanged data.
- **Incremental AI:** one new certificate triggers only the Learning module and the affected resume section — not full regeneration. Event-scoped recomputation, milliseconds not seconds.
- **Queue everything heavy:** upload returns dashboard in <2s with quick validation; GitHub indexing, portfolio scan, deep analysis run in background with progressive dashboard updates + completion notification.
- **Parallel fan-out:** resume, GitHub, JD, portfolio analyses run concurrently and merge.
- **Independent scaling:** resume-generation spikes cannot starve interview prep — separate services, separate autoscaling.
- **SLOs:** dashboard first paint < 2s p95; full first analysis < 30s p95; incremental update < 500ms p95; AI cost per active user tracked per request via observability (§9).

---

## 9. Observability

Every request carries: `trace_id, decision_id (if AI), latency per hop, health status, fallback used, recovery used, AI token cost, errors, confidence`. Dashboards: Mission Health Score, fallback activation rate, HITL acceptance rate by tier (a rising rejection rate is a model-quality alarm), cost per user, funnel progression (North Star). Every incident links to its FMEA row.

---

## 10. Security & Privacy by Design

- **Trust boundaries:** Experience Layer is untrusted; Gateway validates everything; Integration Service is the only egress path; LLMs never call external APIs directly — `AI → MCP Router → authorized tool → verified response → AI` (permissioned, auditable, testable).
- **Least privilege:** per-service credentials; MCP tool allow-lists per mission type.
- **Data:** encryption in transit and at rest; Twin data is user-owned — full export and hard delete (event log cryptographic tombstoning); outcomes are opt-in and separately consented; no cross-user data use without explicit consent; PII never in logs or URLs; secrets in a managed vault, never in code.
- **AI safety:** prompt-injection surface minimized because models receive structured evidence, not raw user documents, wherever possible; all model outputs schema-validated before persistence; uploaded files sandboxed and scanned.
- **Audit:** the Decision Audit doubles as the compliance trail.

---

## 11. Validation Plan (resolving the existential risk honestly)

The claim "recommendations improve outcomes" is unproven until measured. Plan:

1. **Instrument from day one:** every recommendation → action taken? → outcome (consented). The Decision Audit already captures this; no extra system needed.
2. **Proxy metrics before longitudinal data:** HITL acceptance rate, evidence-creation completion rate per recommendation, alignment-score movement per user per month.
3. **Cohort comparison at scale:** users who complete recommended Career Investments vs. matched users who don't, on interview-callback rate. Presented as observational correlation until an A/B design is ethical and feasible.
4. **Pitch language until proven:** "designed to be measurable" — never "proven to work." All claims stay defensible.

---

## 12. MVP — The Hackathon Vertical Slice

Build exactly this, polished, nothing more:

```text
1. Upload resume (PDF/DOCX/paste; 4-stage fallback chain LIVE in demo)
2. Career Twin created; extraction confidences visible; one low-confidence
   fact triggers a human checkpoint ("Did you really reduce latency 40%?")
3. Evidence Scorecard rendered from Twin + GitHub (MCP) — one certificate-only
   skill visibly scored Medium to demonstrate the invariant
4. Paste one target job description → Gap Analysis → Alignment Score with
   limiting factors and improvement estimates
5. One Career Investment recommendation with evidence + ROI
   ("Docker: ~8h; appears in 73% of your matching JDs; currently unverified")
6. Company-adapted resume: AI draft → diff view → per-hunk accept/reject →
   new immutable version → export
7. Decision Replay: judge clicks any recommendation → full reasoning path
8. Kill switch demo: disable the primary LLM live → rule-engine fallback
   answers → Mission Health dashboard shows the degradation and recovery
```

**Demo script (4 minutes):** 30s problem → 60s upload-to-scorecard → 60s gap + investment → 45s resume diff + approval → 30s Decision Replay → 15s live failure + graceful degradation. Steps 7–8 are what no competing team shows.

**Reference implementation (deliberately boring, load-bearing tech):** FastAPI services; PostgreSQL (event log + projections; `pgvector` for RAG — one database, two capabilities, KISS at MVP scale); Neo4j *or* Postgres-recursive-CTE graph for GraphRAG (CTE acceptable at MVP scale; Neo4j when multi-hop latency demands it); Redis (cache + queue backend); Celery workers; MCP servers for GitHub/storage/email; React SPA. Every choice is replaceable behind a service interface — reversible decisions preferred.

---

## 13. Flywheel & Moat

```text
Career Twin → Gap Analysis → Decision Intelligence → Career Investment
→ Evidence Creation → Evidence Verification → Resume Generation
→ Application & Interview → Outcome (consented) → Twin Update
→ Better recommendations → repeat
```

**Moat (in order of durability):** (1) the longitudinal Career Twin + Evidence Graph per user — switching cost grows with every verified artifact; (2) the outcome-linked Decision Audit corpus — proprietary understanding of which recommendations precede which outcomes; (3) trust architecture (explainability, HITL, replay) — a culture-and-design moat competitors must rebuild, not a feature they can bolt on. **Not the moat:** any LLM, RAG, GraphRAG, or MCP — all commodities, framed in the pitch as engineering decisions that each eliminate a named failure mode (§4, §7, §10).

---

## 14. CTO / Judge Q&A (pre-answered)

| Question | Answer |
|---|---|
| Why does this exist? | Careers are managed by guesswork across disconnected tools; CDIS unifies decision, evidence, and outcome in one explainable loop. |
| Why won't ChatGPT replace it? | Chat answers questions; CDIS maintains a persistent, verified, longitudinal model of the user and learns from real outcomes. The LLM is a component. |
| What's the moat? | §13 — Twin + Evidence + Outcome loop, not the models. |
| How do you prevent hallucination? | Structured evidence in, citation-required out, schema validation, HITL tiers, rule-engine fallback, full replayability. |
| What if AI vanishes? | §3.3 — a durable system of record remains. |
| How do you know it works? | §11 — instrumented from day one; honest proxy metrics until longitudinal data exists. |
| What's the hardest problem? | Keeping the Twin accurate over time (skill decay, goal drift) — solved by event sourcing + evidence expiry + periodic re-verification prompts. |
| 10-year vision? | The trusted decision-intelligence layer for a professional lifetime — internships → promotions → leadership → founding. Same Twin, growing with the user. |

---

## 15. System Principles (final, ten)

1. The Career Twin is the single source of truth.
2. AI recommends; humans approve all critical actions; AI never acts irreversibly.
3. Every recommendation ships with evidence, confidence, and expected impact — and is replayable.
4. Every achievement is backed by verified evidence; certificates alone never suffice.
5. Every critical service has health check, fallback, and recovery; services fail independently.
6. Every expensive computation happens once; all recomputation is incremental and cache-aware.
7. All heavy work is asynchronous; the user never waits for deferrable work.
8. Everything is versioned; nothing is overwritten; rollback is always possible.
9. Every claim the product makes about itself must be defensible in technical due diligence.
10. The system optimizes verified career outcomes — not resumes, scores, or engagement.
