# AJAA — Pre-Implementation Architecture & Execution Plan

> **Status:** PLANNING ONLY — awaiting explicit user approval before any code is written.
> **PRD version read:** AJAA-PRD.md (7,163 lines, 464,430 bytes) — read in full.
> **Date:** 2026-09-06

---

## 1. PRD Understanding

### 1.1 What AJAA Is

AJAA is a **local-first, single-candidate-per-installation, open-source desktop application** that automates the mechanical work of a job search. It is not a job board, not a talent marketplace, not a multi-tenant SaaS product, and not a general-purpose computer-use agent.

The product installs once per candidate, stores all data locally on their machine, and requires no authentication system. Python 3.12+ is the sole runtime.

### 1.2 The Two Numbers That Must Never Be Confused

| Concept | Purpose | Default |
|---|---|---|
| **Safety ceiling** | Engineering guard rail — prevents runaway execution | Conservative non-null number |
| **Operational policy** | User volume/quality preference | **null — deliberately unset** |

These two concepts are permanently separated (PRD §26.1). Every part of the system that touches application volume must handle them as distinct concerns.

### 1.3 Hard Non-Goals (Enforced in Code, No Config Flag)

- LinkedIn automation — ToS violation; account ban risk.
- Workday connector — per-tenant accounts + long wizards. Discovery only.
- CAPTCHA solving, bypassing, or outsourcing.
- Account creation on any site on the user's behalf.
- Consent checkbox auto-checking (v0.1-v0.2).
- Behavioral question generation — fabricating a personal anecdote.
- Raising safety ceilings via any rule or config option.
- Telemetry of any kind.

### 1.4 The Candidate Model (Core Insight)

A CV is an **artifact**, not the candidate. The candidate is:
- **Layer 1:** Fact Ledger — append-only, precedence-ordered, typed facts with provenance
- **Layer 2:** CanonicalProfile — derived deterministically from the ledger

A new CV can upgrade CV_* facts but can only *conflict* with USER_* facts. Absence of a fact from a new CV is NEVER treated as deletion.

### 1.5 What v0.1 Must Prove

v0.1 is an **architecture validation release**. Definition of done: a 13-step fresh-clone criterion plus an automated equivalent for four synthetic candidates from unrelated occupations.

---

## 2. Repository Assessment

The project folder contains exactly **one file**: AJAA-PRD.md (464,430 bytes, 7,163 lines).

No existing code, dependencies, configuration, tests, scripts, lock files, or .git directory. Greenfield project. No technical debt.

Phase 0 must establish the entire foundation from scratch.

---

## 3. Proposed Architecture

### 3.1 Architectural Choices

| Decision | Choice | Reason |
|---|---|---|
| Language | Python 3.12+ | Playwright Python first-class; embedding/parsing ecosystem Python-native |
| Package manager | uv | Fast, single-tool, lockfile discipline |
| Web framework | FastAPI | Async-native, Pydantic-integrated, serves HTML and JSON |
| Frontend | Jinja2 + HTMX + Alpine.js + Tailwind standalone CLI | Zero build step, zero npm |
| Database | SQLite WAL + sqlite-vec + FTS5 | Zero ops, trivially backed up, one writer |
| ORM | SQLAlchemy 2.0 async + Alembic | Migrations on a long-lived personal DB are valuable |
| Background execution | APScheduler (AsyncIO) in-process | No broker; SQLite is the queue |
| Browser automation | Playwright for Python 1.62+, Chromium, persistent contexts | Native aria_snapshot; best-in-class tracing |
| LLM access | LLMGateway protocol, OpenAI-compatible HTTP client | Provider-agnostic; any gateway is a config example |
| Embeddings | EmbeddingGateway, local multilingual model (BGE-M3), sqlite-vec | Free; private; multilingual |
| Secrets | OS keychain via keyring + non-stringifiable Secret type | Native OS protection; prevents prompt/log leakage |

### 3.2 Rejected Alternatives

| Alternative | Rejected because |
|---|---|
| React/Vite SPA | Build step + second dev server for a single-user localhost app |
| Next.js | SSR nobody needs |
| PostgreSQL | "install Postgres" is a barrier for open-source users |
| Celery + Redis | Two services for tens of items/day |
| Direct vendor SDKs | Couples codebase to one vendor |
| browser-use / Stagehand | Optimize for zero-shot generality; this system needs determinism for irreversible actions |

---

## 4. Domain Module Boundaries

### 4.1 The Fundamental Rule

No engine module imports a fact repository, CV store, ontology loader, or policy loader directly. Every engine receives a CandidateContext.

This rule is enforced by an import-graph test in CI (test_import_graph_candidate_context).

### 4.2 Module Map

```
src/ajaa/
  types.py                  FIRST FILE. Secret, Untrusted[str], enums, sentinels.
  candidate/
    context.py              CandidateContext frozen dataclass
    facts.py                Fact model, FactStore, precedence resolver
    profile.py              CanonicalProfile projection + hash
    overrides.py            scoped overrides
    ontology.py             competency ontology loader
    coverage.py             coverage calculator
    precedence.py           MOST-TESTED FILE IN THE REPO
  cv/                       CV lifecycle (upload, parse, extract, validate, reconcile)
  interview/                coverage-driven onboarding (NOT an LLM agent)
  discovery/
    sources/
      base.py               JobSource protocol
      greenhouse.py
      lever.py
      ashby.py
      adzuna.py
      paste.py              manual paste-in (highest value-per-hour feature)
    query_plan.py
    politeness.py
  normalization/            job normalization
  dedup/                    deduplication (3-stage cascade)
  matching/                 matching engine (gates + scores + semantic + adjudication)
  application/
    state_machine.py        20 states, all transitions, all guards
    planner.py              PREPARING: all expensive work before browser opens
    executor.py             STARTED -> SUBMITTED orchestration
    connectors/
      base.py               Connector protocol
      greenhouse.py         first deterministic connector
      generic.py            Tier 2 generic form agent (v0.2)
  answering/
    classifier.py
    resolver.py             deterministic resolution for 19 of 22 question types
    polarity.py             SECOND MOST-TESTED FILE
    validate.py             grounding validator (deterministic code, not prompting)
    cache.py
  db/
    models.py               28 SQLAlchemy models
    repositories/           the Postgres migration seam (PRD §28.3)
    migrations/             Alembic
  browser/
    context.py              launch_persistent_context wrapper
    perception.py           ARIA snapshot -> FormDescriptor
    actions.py              fill, click, upload (deterministic; LLM does NOT execute)
    allowlist.py            navigation route interceptor
  llm/
    gateway.py              LLMGateway protocol, routing, retries, cost logging
    prompts/                versioned .md prompt templates (no candidate content)
    builder.py              3-channel prompt builder, Untrusted enforcement
    schemas.py              Pydantic response models for all 6 call sites
    injection.py            prefilter patterns + detection
  secrets/
    keyring_store.py        ONLY module that touches the OS keychain
  obs/
    logging.py              structlog + redaction processor
    events.py               append-only audit chain
  orchestration/            APScheduler, run lifecycle, pipelines, control
  web/                      FastAPI, routes, Jinja2 templates, static
```

---

## 5. Data Model

### 5.1 The 28 Tables

```
CANDIDATE
  candidate_context    EXACTLY ONE ROW. Provenance owner. Not a tenant key.
  facts                Append-only. NEVER deleted. STATUS=SUPERSEDED instead.
                       DB CONSTRAINT: source=LLM_INFERENCE => usable_in_applications=0
  fact_conflicts       Unresolved conflicts awaiting user decision.
  fact_overrides       Scoped overrides (per-job, per-employer).
  profile_snapshots    Materialised projection + version_hash. Cache key for downstream.
  unmapped_terms       Queue for all four domain-data families.

CV
  cvs                  Logical variants. UNIQUE(label per candidate).
  cv_versions          Immutable uploaded files. UNIQUE(content_sha256).
  extraction_runs      One extraction attempt. Raw output retained for audit.
  reconciliation_reports  NEW / CHANGED / CONFLICT + silent_absences (informational only).

JOBS
  ats_tenants          UNIQUE(ats_type, board_token).
  job_sources          compliance_json REQUIRED. Refuses to load without it.
  jobs                 UNIQUE(fingerprint). FTS5 on title + description.
  job_sightings        UNIQUE(source_key, source_job_id).

MATCHING
  match_results        UNIQUE(job_id, profile_version_hash, ontology_version, policy_version).
  job_feedback         Ongoing calibration signal.
  calibration_runs     A completed row unblocks auto-apply. No completed row = blocked.

APPLICATIONS
  applications         UNIQUE INDEX (job_id) WHERE status NOT IN (CANCELLED,SUPERSEDED).
                       cv_content_sha256 recorded so "what did I send?" is answerable years later.
  application_steps    ok=NULL means outcome unknown (crash between commit and action).
  application_questions
  application_answers  grounded_fact_ids recorded. Every claim traceable to a fact.
  pending_questions    NEEDS_USER queue.

CACHES
  field_signatures     Stores MAPPING (field -> key_path). NEVER stores a value. No PII.
  answer_cache         Key includes prompt_version (a prompt change invalidates the cache).

COMMS
  cover_letters        grounded_fact_ids + was_edited + edited_text.

OPS
  runs
  agent_events         Append-only, hash-chained: hash = sha256(prev_hash || canonical_json(event))
  llm_calls            Every call logged BEFORE returning: tokens, cost, prompt_version, cache_hit.
```

### 5.2 Critical Schema-Level Invariants

1. facts: CHECK constraint: source=LLM_INFERENCE => usable_in_applications=0 (database, not app logic).
2. cv_versions: UNIQUE(content_sha256) — re-uploading identical bytes is a no-op.
3. applications: partial unique index on job_id excluding terminal states — duplicate submissions structurally blocked.
4. calibration_runs: no completed row -> auto-apply is blocked.

### 5.3 Blob Store (OUTSIDE the repository working tree)

```
<user data dir>/ajaa/
  ajaa.db (+ wal, shm)
  cvs/{content_sha256}.{ext}      immutable, addressed by hash
  extractions/{run_id}.json       raw model output for audit
  artifacts/{application_id}/    screenshots, aria snapshots, traces
  emails/{application_id}.eml
  browser_profiles/{profile}/    0700
  logs/ajaa.jsonl  events.jsonl
  backups/ajaa-YYYYMMDD.db
```

Directory permissions: 0700. Database and CV files: 0600.

---

## 6. API Architecture

### 6.1 Route Table

Bound to 127.0.0.1 only. No authentication.

```
GET    /                     dashboard
GET    /jobs                 list + filters
GET    /jobs/{id}            detail + match explanation
POST   /jobs/{id}/queue      enqueue for application
POST   /jobs/{id}/skip       skip + reason (feeds calibration)
POST   /jobs/paste           manual job paste-in

GET    /applications         list
GET    /applications/{id}    replay view (full provenance)
POST   /applications/{id}/approve
POST   /applications/{id}/abandon
POST   /applications/{id}/resolve   resolve UNCERTAIN / NEEDS_USER

GET    /profile              facts + coverage
POST   /profile/facts        add/edit/confirm a fact
POST   /profile/conflicts/{id}
GET    /profile/coverage

POST   /cv                   upload
GET    /cv                   list
POST   /cv/{id}/activate
GET    /cv/{id}/reconcile    diff view

GET    /interview/next
POST   /interview/answer

GET    /questions/pending    NEEDS_USER queue
POST   /questions/{id}/answer

POST   /runs/discover | /runs/match
GET    /runs/{id}
POST   /control/pause | /resume | /panic

GET    /metrics
GET    /settings   POST /settings
```

### 6.2 Dashboard Design (PRD §31.1)

Two headline indicators rendered as **separate** elements (PRD §26.1 explicitly prohibits a single bar):

- SAFETY CEILING: n / cap today — headroom OK/WARNING. Any breach = a bug.
- OPERATIONAL TARGET: "not set — batches approved by hand" OR n / target today. Never alerts.

Below them: MATCH THRESHOLD — uncalibrated / CALIBRATED (n=...) with calibrate action button. Auto-apply is blocked until CALIBRATED.

---

## 7. AI / LLM Architecture

### 7.1 Six Bounded Call Sites

The v0.1 answering engine is fully deterministic. There are exactly 6 LLM call sites:

1. CV extraction — structured output, once per CV version (strong tier)
2. Job requirement extraction — cheap tier, cached permanently by sha256(description_text)
3. Field classification — cheap tier, batched per page
4. Question type classification — cheap tier, fallback only (after pattern classifiers)
5. Match adjudication — mid tier, ambiguous band only (v0.2)
6. Grounded open-ended answer generation — strong tier (v0.2)

No agentic loop. No unbounded reasoning. No call site that can recurse.

### 7.2 The 3-Channel Prompt Architecture

```
SYSTEM    -- static, in git, versioned. NEVER contains candidate content.
CONTEXT   -- trusted runtime candidate facts assembled from CandidateContext.
UNTRUSTED -- job description, form labels, question text. Always delimited.
```

Untrusted content is NEVER concatenated into the SYSTEM channel. Untrusted[str] type enforces this at the type level; the builder rejects it outside the untrusted block.

### 7.3 Injection Defense (7 Layers)

1. Capability restriction — the model has no tools; output is a small JSON schema.
2. Channel separation — untrusted content in its own delimited section.
3. Output constraints — strict Pydantic schemas; out-of-enum values are validation errors.
4. Output allowlisting — generated values must cite a fact or pass the grounding validator.
5. Navigation allowlist — browser may only navigate to the apply host.
6. Detection and quarantine — injection_suspected flag + regex prefilter.
7. Never auto-submit a quarantined job.

The model's inability to take actions is the actual defense. Detection is secondary.

### 7.4 Local Embeddings

Default: BGE-M3 (or current equivalent) via sentence-transformers/fastembed. Multilingual (1024-dim), 8k context, runs on CPU. Stored in sqlite-vec. Profile text and job descriptions never leave the machine under the default configuration.

---

## 8. Browser Automation Architecture

### 8.1 The Tiered Strategy

```
TIER 1 — Deterministic connectors   ~85% of ATS-covered volume
  ~0 LLM calls, ~95% success rate, 30-60s per application
  Greenhouse / Lever / Ashby (and more in v0.2)

TIER 2 — Generic form agent          ~10-15% (v0.2)
  PERCEIVE -> CACHE -> MAP -> RESOLVE -> PLAN -> EXECUTE -> VERIFY
  LLM proposes field mappings only. Deterministic code executes.
  Max 6 recovery iterations. RecoveryAction is a closed enum.

TIER 3 — Human handoff               ~5-10%
  Full artifact bundle: URL, pre-computed answers, CV, screenshot, reason.
  User completes the application in ~90 seconds.
```

### 8.2 The UNCERTAIN State

The most critical state in the system. Submit click succeeded but no confirmation detected.
- NEVER auto-retry from UNCERTAIN — this is how duplicate applications happen.
- Human resolves, always.
- Expected rate: 3-8% on Tier 2.

### 8.3 Safety in the Browser

- Navigation allowlist enforced per application (browser may only go to the apply host).
- RecoveryAction is a closed enum: DISMISS_MODAL, SCROLL_TO, RETRY_FIELD, GO_BACK, ESCALATE_VISION, ABORT. No NAVIGATE. No EXECUTE_JS.
- CAPTCHA -> always halt to BLOCKED_BY_SITE. No solving, no bypassing.

---

## 9. CV Document Pipeline

### 9.1 Lifecycle

```
UPLOAD -> PARSE -> EXTRACT -> VALIDATE -> RECONCILE -> ACCEPT/RESOLVE -> ACTIVATE
```

Every stage is idempotent and re-runnable except ACTIVATE.

### 9.2 Reconciliation Contract

| Ledger state | New CV says | Bucket | Action |
|---|---|---|---|
| No fact | a value | NEW | Accept |
| CV_* fact, same value | same | unchanged | Nothing |
| CV_* fact, different value | a value | CHANGED | Accept |
| USER_* fact, different value | a value | CONFLICT | Ask user — NEVER auto-resolve |
| LLM_INFERENCE fact | a value | CHANGED (upgrade) | Accept |
| Any fact | omission (silent) | none | NOTHING. Recorded in silent_absences. |

The last row is the most important invariant in the CV pipeline (PRD FR-CV-09).

---

## 10. Human Approval Model

### 10.1 Action Classification

| Class | Examples | Gate |
|---|---|---|
| AUTO | Read pages, fill non-sensitive fields, upload CV, take screenshots | Agent, unattended |
| AUTO-WITH-POLICY | Submit an application | Agent, only when all never_auto_submit_if conditions clear |
| CONFIRM | Submit while review enabled; sensitive field; contested fact | Human, per instance |
| NEVER | Create account; check consent box; solve CAPTCHA; generate behavioral answer; raise safety ceiling | Prohibited in code. No config flag. |

### 10.2 The never_auto_submit_if Floor (Not Overridable by Any Rule)

- unanswered_required_questions_exist
- any_answer_confidence_below_type_floor
- consent_checkbox_present_without_prior_grant
- job_quarantined_for_suspected_injection
- calibration_not_completed                    <- the auto-apply gate
- connector_trust_period_not_elapsed

### 10.3 The Calibration Gate

Auto-apply is not merely discouraged before calibration — it is impossible. calibration_not_completed is in never_auto_submit_if. The only way to satisfy it is to run the calibration protocol: label 80-120 jobs, choose a threshold from the precision/recall curve.

---

## 11. Security Architecture

### 11.1 The Secret Type

```python
class Secret:
    def __repr__(self): return "<Secret redacted>"
    def __str__(self): raise TypeError("Secret cannot be stringified")
    def reveal(self) -> str: ...  # <= 2 call sites, enforced by a lint rule
```

reveal() appears in exactly two places: the browser login helper and the SMTP client.

### 11.2 PII Classification

| Class | Examples | Rule |
|---|---|---|
| P0 -- professional | Employers, titles, dates, competencies | Free use in prompts and logs |
| P1a -- identity | The candidate's own name | Redacted from logs and screenshots |
| P1b -- contact | Email, phone, address | Sent only to destination field. Redacted from logs. |
| P2 -- sensitive | Date of birth, nationality, national ID | Never in a prompt. Never volunteered. |
| P3 -- secret | Passwords, API keys, session cookies | Secret type. Never near a model or a log. |

### 11.3 Audit Hash Chain

agent_events table: hash = sha256(prev_hash || canonical_json(event)). Tamper-evident. JSONL mirror on disk provides redundancy.

### 11.4 The 10 Anti-Fabrication Invariants

| # | Invariant | Test |
|---|---|---|
| I1 | No answer contains an uncited fact | test_grounding_rejects_uncited_entities |
| I2 | No numeric claim exceeds the derived maximum | test_years_capped_by_career_length |
| I3 | No boolean authorization answer without CONFIRMED fact + matched polarity pattern | test_sponsorship_polarity_matrix |
| I4 | No behavioral answer generated | test_behavioral_always_needs_user |
| I5 | No P2 field filled unless required and opted-in | test_p2_never_volunteered |
| I6 | No consent checkbox auto-checked (v0.1-v0.2) | test_consent_checkbox_halts |
| I7 | No submission twice for one canonical job | test_duplicate_submit_blocked |
| I8 | No secret stringified into any prompt or log | test_secret_cannot_stringify |
| I9 | No untrusted string placed outside the UNTRUSTED block | test_prompt_builder_rejects_untrusted_in_system |
| I10 | No navigation outside the per-application allowlist | test_navigation_allowlist |

---

## 12. Queue / Background-Job Architecture

**APScheduler (AsyncIO) + asyncio.Semaphore worker pool, in-process. SQLite is the queue.**

No Redis, no Celery. The migration trigger is documented (PRD §28.3): SQLITE_BUSY in logs, or multi-machine operation.

Pipeline: DISCOVER -> NORMALIZE -> MATCH -> APPLY

Watchdogs:
- Per-step timeout: capture artifacts, classify, transition.
- Per-application timeout: 8 min. Hard abort.
- Per-run timeout: 90 min.
- Lock reaper: any locked_at older than 15 min is released and re-queued.
- Heartbeat: run manager writes a row every 30s.

Controls: POST /control/pause | /resume | /panic

---

## 13. Testing Architecture

### 13.1 The Pyramid

```
      /\           Manual exploratory (periodic)
     /  \          Real-site smoke: one DRY-RUN per connector, weekly
    /----\
   /      \        E2E against local fake sites (~25 scenarios, v0.2)
  /--------\
 /          \
/ Multi-     \     Genericity suite -- 4 synthetic candidates, CI-BLOCKING
/--------------\
| Integration  |   ~80 tests, mocked LLM, frozen fixtures
|--------------|
|    Unit      |   ~400 tests -- pure functions
|______________|
```

### 13.2 The Genericity Suite (CI-Blocking)

Four fully-invented synthetic candidates from unrelated occupations:

| | A | B | C | D |
|---|---|---|---|---|
| Occupation | Software engineer | Marketing manager | Mechanical engineer | Registered nurse |
| Credential-bearing | No | No | No | Yes (professional license) |
| Target market | International remote | EU multi-country | US industrial | UK NHS |
| Discovery | Greenhouse/Lever | LinkedIn (paste-in) | Aggregators | NHS jobs (paste-in) |

This is the test that proves the architecture rather than the installation.

### 13.3 The Adversarial Suite (CI on Every Commit)

12 malicious job descriptions + 1 false-positive control (a real prompt-engineering job ad that must NOT trigger quarantine). This is the only test that protects against the highest-impact failure mode.

### 13.4 High-Value Unit Tests (Acceptance-Criterion Level)

- Fact precedence: every source-rank pair; USER_* cannot be superseded by CV_* or LLM_INFERENCE.
- Polarity guard: >= 40 real authorization/sponsorship phrasings x both fact values x every shipped locale. Unmatched phrasings must yield NEEDS_USER, never a guess.
- Grounding validator: uncited entity -> reject; uncited number -> reject.
- Secret type: cannot stringify, cannot repr, cannot JSON-serialize; reveal() call-site count.
- Untrusted[str]: prompt builder rejects it outside the untrusted block.
- Policy engine: safety: is non-overridable by any rule; ceilings enforced at all three layers.
- State machine: every legal transition; every illegal transition raises; SUBMITTING never re-entered.

---

## 14. Observability Architecture

Structured logging (structlog -> JSONL) with PII redaction processor that scrubs P1a/P1b/P1c/P2/P3 before write, including the candidate's name.

Every LLMGateway call writes an llm_calls row BEFORE returning: tokens, cost, prompt_version, cache_hit.

Application replay view (PRD §31.2): every submitted application is fully auditable with timeline, fact citations, CV hash, LLM call details, screenshots, ARIA snapshots, and provenance hashes.

---

## 15. Exact Folder Structure

```
<repo>/
  .github/workflows/
    ci.yml                ruff, mypy, unit, integration, adversarial, genericity
    weekly-canary.yml     weekly dry-run per connector

  configs/                SHIPPED TEMPLATES (user copies to config dir)
    providers.example.yaml
    policy.example.yaml
    sources.example.yaml
    matching.example.yaml
    settings.example.yaml

  data/                   SHIPPED DEFAULTS (data files, not code)
    ontology/
      core.yaml           occupation-neutral competencies only
      packs/              contribution surface (v0.2+)
    coverage/core.yaml
    questions/core.<bcp47>.yaml
    polarity/authorization.<bcp47>.yaml   >= 40 phrasings per locale
    titles.yaml
    seniority.yaml
    education_levels.yaml
    legal_suffixes.yaml
    manual_only_hosts.yaml
    redflags/<bcp47>.yaml
    field_patterns/<bcp47>.yaml
    ats_tenants.seed.yaml   small generic starter list, labelled as demo aid

  src/ajaa/               (see Module Map in §4.2)

  tests/
    unit/                 ~400
    integration/          ~80, mocked LLM
    e2e/                  fake-site scenarios (v0.2)
    adversarial/          12-file injection corpus
    genericity/           4-candidate suite (CI-BLOCKING)
    fixtures/
      candidates/{a,b,c,d}/   SYNTHETIC profiles, CVs, jobs
      cvs/awkward/            two-column, table-heavy, non-Latin, image-only
      sources/                frozen PUBLIC API responses
      forms/                  scrubbed DOM + aria snapshots
      questions/              ~150 real form WORDINGS (no candidate data)
    fakesites/            local fake ATS sites (v0.2)
    conftest.py

  scripts/
    make_fixtures.py      generates synthetic candidates + CVs
    seed_tenants.py
    capture_fixture.py    with mandatory redaction pass
    backup.py
    verify_audit_chain.py

  docs/IMPLEMENTATION-PLAN.md
  pyproject.toml
  uv.lock
  .pre-commit-config.yaml   gitleaks + ruff + mypy
  .gitignore                covers data dir, configs, browser profiles, artifacts
  README.md
  CONTRIBUTING.md           includes compliance policy for source contributions
  LICENSE
```

Data directory (OUTSIDE the repo, enforced at startup):
```
<user config dir>/ajaa/   e.g. ~/.config/ajaa or %APPDATA%\ajaa
  providers.yaml
  policy.yaml
  sources.yaml
  matching.yaml
  settings.yaml
  data/                   user overlays for EVERY shipped data family

<user data dir>/ajaa/     e.g. ~/.local/share/ajaa or %LOCALAPPDATA%\ajaa
  ajaa.db (+ wal, shm)
  cvs/ artifacts/ emails/ browser_profiles/ logs/ backups/

OS keychain               every secret, always
```

---

## 16. Git Strategy

- main — always green; CI must pass before merge.
- phase-N/description — one branch per implementation phase.
- Pre-commit hooks: gitleaks (BEFORE first secret), ruff, mypy --strict, test_no_personal_strings_in_source.
- CI on every PR: ruff, mypy, unit, integration, adversarial corpus, genericity suite.
- Weekly CI: one dry-run per connector against a live posting.

What must NEVER be committed: API keys, any real person's CV or facts, browser profiles, screenshots with PII, log files from real runs, database files, the maintainer's personal details in source or prompts.

---

## 17. Implementation Phases with Acceptance Criteria

Rule: Do not start Phase N+1 until Phase N's acceptance criteria pass. Every phase ends with something that runs and is independently useful.

---

### Phase 0 — Foundation (3-4 days)

Goal: a repo that runs, tests, migrates, and logs.

Deliverables:
- uv project with lock file.
- types.py — FIRST FILE: Secret, Untrusted[str], FactSource, Confidence, FactState, ApplicationState.
- SQLAlchemy 2.0 async + Alembic + SQLite WAL.
- structlog with PII redaction processor.
- Layered config loading: Pydantic Settings + YAML + schema validation.
- First-run bootstrap: creates dirs OUTSIDE repo; REFUSES to start if they resolve inside it.
- keyring wrapper.
- pytest + pytest-asyncio + coverage + hypothesis.
- ruff + mypy --strict.
- Pre-commit with gitleaks (installed BEFORE any secret exists).
- FastAPI skeleton (one route returning 200).
- LLMGateway + EmbeddingGateway with cost logging.
- ajaa doctor — probes provider, reports model IDs, structured output support, pricing.
- ajaa init CLI command.
- Technical spikes V-01 through V-10.

Acceptance criteria:
- uv run pytest green.
- ajaa init creates directories OUTSIDE the repo; ajaa doctor confirms this.
- Data directory configured inside repo -> startup refusal.
- ajaa serve returns a page.
- One real model call logged to llm_calls with tokens and a computed cost.
- test_secret_cannot_stringify passes.
- test_prompt_builder_rejects_untrusted_in_system passes.
- Malformed policy.yaml -> startup refusal.
- V-10 spike passes: clean-machine clone reaches first-run wizard without editing source.

Risks: Run spike V-01 (provider structured-output support) and V-10 (clean-machine bootstrap) here, before anything depends on them.

---

### Phase 1 — Candidate Knowledge Base (4-6 days)

Goal: facts in, correct profile out.

Deliverables:
- Fact, FactOverride, fact_conflicts models + Alembic migrations.
- Precedence resolver (most-tested module in the project).
- Profile projection + profile_version_hash.
- CandidateContext frozen dataclass + the import-graph test.
- Competency ontology loader: core.yaml + user-local additions.
- Coverage calculator.
- CRUD API + Jinja/HTMX profile screen: fact editing, source badges, confidence badges, conflict resolution.

Acceptance criteria:
- Full precedence unit-test matrix passes.
- CV_* fact cannot override USER_* fact; can only raise a conflict.
- LLM_INFERENCE facts forced usable_in_applications=false at write time (DB CHECK constraint).
- All four FactState values (KNOWN, UNKNOWN, REFUSED_TO_ANSWER, NOT_APPLICABLE) behave correctly.
- Projection is deterministic: same facts -> same hash, verified over 100 randomised runs.
- profile_version_hash covers schema version and ontology version.
- custom{} preserves unmodelled key paths.
- test_import_graph_candidate_context passes.
- Profile screen: edits, confirms, resolves conflicts.

Risks: key_path taxonomy churn. Mitigate by writing the PRD §11.8 schema first and treating it as an interface.

---

### Phase 2 — CV Lifecycle (4-5 days)

Goal: full CV lifecycle — upload, parse, extract, validate, reconcile, activate, archive.

Deliverables:
- Upload with content-hash dedup.
- Text extraction with explicit, actionable failure for image-only PDFs.
- Deterministic VALIDATE stage that drops and reports bad observations before they reach the ledger.
- Structured extraction with raw output retained at extractions/{run_id}.json.
- extraction_runs and reconciliation_reports tables.
- Three-bucket reconciliation UI (NEW, CHANGED, CONFLICT).
- silent_absences recorded and displayed (informational only).
- Archive-not-delete behaviour.
- Zero-CV operation: profile built from interview alone is a supported state.
- scripts/make_fixtures.py + four synthetic candidates' CVs.

Acceptance criteria:
- Every synthetic CV extracts to its expected fact set.
- Re-uploading identical bytes is a no-op (UNIQUE constraint enforced).
- Image-only PDF produces a clear error, not silent garbage.
- Validation drops bad observations and reports them; does NOT silently coerce.
- Full reconciliation contract holds for every row (including: USER_* conflict is never auto-resolved).
- silent_absences never drives any ledger change.
- User-confirmed facts survive CV replacement; conflicts raised, not silently resolved.
- Facts that a new CV omits are NOT deleted from the ledger (PRD FR-CV-09).

---

### Phase 3 — Onboarding Interview (2-3 days)

Goal: coverage-driven questioning that terminates and never re-asks what it already knows.

Deliverables:
- coverage/core.yaml and questions/core.<bcp47>.yaml.
- Coverage calculator against the fact ledger.
- Priority-queue scheduler (deterministic; NOT an LLM model).
- Interview UI: one question at a time, typed answers, progress indicator.
- Typed-input fallback when no LLM is configured.

Acceptance criteria:
- Interview terminates within the configured question budget.
- A slot with confidence >= HIGH is never re-asked.
- UNKNOWN and REFUSED_TO_ANSWER are recorded states that prevent re-asking.
- NOT_APPLICABLE slots score zero and are never raised again.
- With no LLM configured, interview runs using raw templates.

---

### Phase 4 — Job Discovery (4-5 days)

Goal: a daily deduplicated feed of relevant postings.

Deliverables:
- JobSource protocol.
- Source adapters: Greenhouse, Lever, Ashby, one aggregator, manual paste-in.
- ats_tenants + job_sources tables.
- Compliance enforcement at load time (source without compliance block refuses to load).
- Politeness layer: token bucket per host, robots.txt caching, 429 handling, circuit breaker.
- Normalization pipeline: title, employer, location, salary, apply-route detection.
- HARD GATES FIRST pipeline ordering (gates run before any LLM extraction).
- Description-hash cache (same description text extracted exactly once, for life of installation).
- Fingerprint deduplication (stages 1 and 2).
- Embedding of normalized jobs (local model).
- manual_only_hosts.yaml with user overlay support.
- Discovery UI: filterable job list.

Acceptance criteria:
- Source without compliance block refuses to load at runtime.
- test_source_requires_compliance_block passes.
- Politeness layer: rate limits respected; robots.txt fetched and honoured.
- Hard gates run before extraction (pipeline ordering verified by test).
- Description-hash cache: same description text extracted exactly once.
- Manual paste-in produces a canonical Job with full downstream treatment (normalization, dedup, embedding, matching).

---

### Phase 5 — Matching Engine + Calibration (4-5 days)

Goal: honest ranking of discovered jobs against the candidate profile.

Deliverables:
- Stage 0: hard gates with machine-readable reason codes (12 gates).
- Stage 1: weighted structured sub-scores (competency, title, experience, location, education, compensation).
- Stage 2: semantic score via local embeddings.
- Calibration harness: stratified sample, labelling UI, precision/recall curve, threshold selection.
- calibration_runs table.
- The auto-apply gate: calibration_not_completed in never_auto_submit_if.
- Match result UI with breakdown on hover.
- MatchResult.threshold_status always visible: CALIBRATED(n=N) or UNCALIBRATED.

Acceptance criteria:
- Every gate produces the correct reason code for its test case.
- Competency scoring: no soft credit for credential-bearing requirements (PRD §11.7).
- threshold_status is UNCALIBRATED until calibration completes; auto-apply is blocked.
- After calibration: CALIBRATED(n=N) shown; auto-apply becomes available (still gated by review policy).
- Scoring is monotonic: adding a matched competency never lowers the score (property-based test).
- Sub-score weights are in config, not code.

---

### Phase 6 — Application State Machine + First Connector (5-7 days)

Goal: one complete, auditable application submitted through one deterministic connector.

Deliverables:
- Full 20-state state machine: all states, all transitions, all timeouts, all guards.
- ApplicationStep persistence: step written to DB BEFORE action; updated AFTER.
- UNCERTAIN state: never auto-retry.
- PREPARING stage: CV selection, answer resolution, freshness check — all before browser opens.
- REVIEW gate: always in v0.1.
- Watchdogs: per-step timeout, per-application timeout (8 min), per-run timeout (90 min), browser process recycling (every 25 applications), lock reaper.
- The Greenhouse connector (or whichever verified as widest-reach + most stable in spike V-03).
- NEEDS_USER queue + batched review UI (10 applications, approve-all button).
- Safety ceiling enforcement at all three layers: scheduler check, queue-drain check, pre-submit DB re-read.
- --dry-run mode: full pipeline without opening a browser or submitting.
- Application replay view with full provenance.

Acceptance criteria:
- test_duplicate_submit_blocked passes.
- SUBMITTING is never re-entered for the same application (property-based test over all reachable state paths).
- UNCERTAIN never auto-retries.
- Safety ceiling enforced at all three layers; any breach logged as an error.
- --dry-run passes for the connector without browser interaction.
- test_navigation_allowlist passes.
- test_consent_checkbox_halts passes.
- Adversarial suite passes in CI (first time for the full suite).
- 13-step fresh-clone criterion (PRD §40.1) passes manually.
- Genericity suite (4 synthetic candidates) passes in CI.

---

### Phase 7 — Hardening (2-3 days)

Goal: production-ready for real use. This is v0.1.

Deliverables:
- Comprehensive ajaa doctor report: directories, provider health, model IDs, structured output support, prompt caching, embedding model, source status, OS keychain, disk encryption warning.
- Graceful degradation: LLM provider down -> Tier 1 + cached answers continue; one source down -> circuit-break and continue; embedding model missing -> structured-only matching with SEMANTIC_UNAVAILABLE flag.
- Backup: nightly VACUUM INTO backups directory; 14-day retention.
- All metrics emitting correctly.
- Dashboard finalized (including separate safety ceiling vs. operational target indicators).
- README, CONTRIBUTING, LICENSE, and compliance policy for source contributions finalized.
- test_no_personal_strings_in_source in CI.

Acceptance criteria:
- Fresh-clone criterion passes for a reviewer who has never seen the repository.
- Genericity suite passes in CI with all four synthetic candidates.
- Zero fabricated claims in a manual audit of 20 real applications.
- ajaa doctor reports every check as OK on a properly configured installation.
- All 10 anti-fabrication invariants pass.

---

## 18. Architectural Risks

Ordered by expected damage (probability x impact):

| ID | Risk | Prob | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | LinkedIn account banned for automation | Near-zero if not attempted | Critical + unrecoverable | Hard prohibition in code, no config flag. Human-assisted paste-in instead. |
| R-02 | High volume, low quality -> user loses trust, system becomes shelfware | High without calibration | Critical | Calibration gate blocks auto-apply; operational volume ships unset; response-rate-by-band tracked from first application. |
| R-03 | Hallucinated answer submitted to real employer | Medium without controls | Critical + invisible | Grounding validator + polarity guard + refusal-by-default. Must be built in Phase 6. |
| R-04 | Screening-question long tail never converges | Medium | High | Just-in-time capture; answer + field-signature caches; convergence curve is an explicit metric. |
| R-05 | ATS UI changes break connectors silently | High (certain over a year) | Medium | Weekly dry-run canary per connector; failure-rate alerting. |
| R-11 | Scope creep — project never ships | High (most likely failure mode) | Critical | Ruthless MVP; every phase independently useful; cut connector breadth to one if needed. |
| R-19 | User commits candidate data to a public fork | Medium | High for that user | Data outside working tree by construction; gitleaks pre-commit; doctor warns if data path inside repo. |
| R-21 | Project works for its author but fails for other occupations | Medium-high if untested | High | Four-candidate CI suite; ontology degrades gracefully; unmapped-term queue surfaces thin coverage. |
| R-22 | Maintainer's needs quietly pull defaults toward one profile | Medium over time | Medium | test_no_personal_strings_in_source in CI; empty filter defaults. |

The four risks that would actually kill the project: R-01, R-02, R-11, and R-19. None is a technical problem. All four are settled by decisions made before any code is written.

---

## 19. ADR Candidates

| ADR ID | Decision | Conclusion |
|---|---|---|
| ADR-001 | LinkedIn automation: ever? | No. Ever. No configuration flag. |
| ADR-002 | Safety ceiling vs. operational policy | Two, permanently separate. |
| ADR-003 | Fact ledger + projection vs. single profile document | Append-only ledger + deterministic projection + scoped overrides. |
| ADR-004 | CandidateContext as the only handle onto candidate data | Code-level enforced rule (import-graph test in CI). |
| ADR-005 | SQLite vs. PostgreSQL | SQLite WAL for v0.1-v0.2. Migration path documented. |
| ADR-006 | In-process APScheduler vs. Celery+Redis | In-process APScheduler. SQLite is the queue. |
| ADR-007 | Browser agent: tiered strategy vs. full LLM agent | Tiered: deterministic connectors -> generic DOM agent -> human handoff. |
| ADR-008 | LLM provider coupling | Provider-agnostic protocol. Any specific gateway is a config example, never a dependency. |
| ADR-009 | Local embeddings vs. API embeddings as default | Local multilingual model default. API embeddings available via config with explicit privacy warning. |
| ADR-010 | Consent checkboxes | Halt in v0.1-v0.2. Per-employer one-time grant in v0.3. |
| ADR-011 | Calibration as a hard gate | Hard gate in never_auto_submit_if. Not merely recommended. |
| ADR-012 | Data inside vs. outside the repository working tree | Outside, by construction. Startup refusal if inside. |
| ADR-013 | Human review gate | Always in v0.1. Earned per-connector with data in v0.2+. |
| ADR-014 | Shipped min_match_score | null. Any shipped number would be a lie. |
| ADR-015 | Frontend: HTMX vs. React SPA | HTMX + Jinja2. React island available as escape hatch for the profile screen only. |

---

## 20. Explicit Assumptions

| ID | Assumption | Impact if false | Verification |
|---|---|---|---|
| A-01 | Greenhouse/Lever/Ashby public APIs return full job descriptions with content=true | Discovery adapters may need HTML scraping fallback | Spike V-02 |
| A-02 | Chosen provider supports strict JSON schema output (not just "try to produce JSON") | Schema-in-prompt + validation + repair-retry becomes the primary path | Spike V-01 |
| A-03 | Local multilingual embedding model (BGE-M3) runs at acceptable speed on CPU | Fall back to API embeddings (with privacy warning) or structured-only matching | Spike V-05 |
| A-04 | sqlite-vec installs cleanly on Windows, macOS, and Linux | Store vectors as BLOBs and brute-force in numpy | Spike V-08 |
| A-05 | Playwright launch_persistent_context preserves sessions across runs | Use storage_state save/load as fallback | Spike V-09 |
| A-06 | First ATS connector's form selectors are stable across multiple tenants | Widen selector strategy; lean on ARIA labels over name attributes | Spike V-03 |
| A-07 | aria_snapshot(mode="ai") output on real ATS forms is usable | Fall back to DOM-query-based FormDescriptor | Spike V-04 |
| A-08 | Chosen aggregator covers more than one country | Rely on ATS APIs + paste-in only for v0.1 | Spike V-06 |
| A-09 | Normal personal mailbox can send via SMTP without spam issues | Different provider or defer email to v0.3 | Spike V-07 |
| A-10 | First-run bootstrap works on a clean machine without editing source | First open-source users fail on install | Spike V-10 |
| A-11 | application_frequency values in coverage/core.yaml are reasonable estimates | Onboarding asks too many or too few questions | Calibrated from real form data in v0.2 |
| A-12 | polarity/authorization.<bcp47>.yaml with >=40 phrasings covers most cases | Sponsorship polarity errors occur in real applications | Test matrix reveals gaps |

---

## 21. Questions That Block Implementation

These must be answered before Phase 0 begins.

### Q-BLOCK-01: Which LLM Provider and Model?

providers.yaml must be drafted before Phase 0 can write the first test that calls LLMGateway. Spike V-01 cannot run without a configured provider.

Needed:
- Provider name and base URL (e.g., OpenAI-compatible endpoint).
- API key -> stored in OS keychain, never in a file.
- Model IDs for cheap, mid, and strong tiers.
- Whether prompt caching is available for that provider.
- Pricing metadata (input/output token costs) for the cost ledger.

Fallback: Phase 0 can run with a mock LLM gateway. But the real provider must be configured before Phase 2 (CV extraction uses the strong tier).

### Q-BLOCK-02: Which ATS Gets the First Connector?

Phase 6 is structured around one connector. Choosing one with unstable selectors costs the most expensive phase an extra week.

Recommendation (PRD D-08): Greenhouse — widest reach, simplest form, most stable selectors. Confirm with spike V-03 (selector stability across tenants).

### Q-BLOCK-03: Which Aggregator (if any) Ships Enabled?

Options:
1. ATS APIs + paste-in only (zero-key first run, simplest).
2. Adzuna with user-supplied key (reference implementation in PRD).
3. Arbeitnow (keyless, narrower coverage, zero-setup).

PRD recommendation (Q-03): option 1 or 3 for v0.1.

### Q-BLOCK-04: Is Windows a Supported Platform?

Keychain integration, path handling, and browser profile paths differ between OSes. Spike V-10 is OS-specific.

Recommendation: Windows as a supported platform from day one (the user is on Windows). macOS in Phase 7. Linux follows.

### Q-BLOCK-05: Which Licence?

Must be decided before publication (PRD Q-01).
- MIT: permissive, widest contributor base.
- AGPL-3.0: copyleft, prevents proprietary hosted versions (strongest protection against NG11 risk).
- Apache-2.0: permissive with patent grant.

### Q-BLOCK-06: Pre-Code Checklist Completion (PRD §45.5)

These items require manual work before Phase 0 begins:

[ ] configs/ templates drafted (providers, tasks, policy, sources, matching).
[ ] ontology/core.yaml drafted — occupation-neutral entries only.
[ ] titles.yaml drafted — role families and synonyms, several domains.
[ ] coverage/core.yaml + questions/core.<bcp47>.yaml drafted.
[ ] polarity/authorization.<bcp47>.yaml drafted with >= 40 real phrasings.
[ ] Screening-question corpus collected (~150 real form wordings, no candidate data).
    NOTE: browsing 20 real application forms by hand is the single most useful
    hour of preparation available before writing any code.
[ ] Four synthetic candidates specified (occupations, credentials, education systems, languages).
[ ] Small generic starter ATS tenant list for first-run demos.
[ ] .gitignore covers the data dir, configs, browser profiles, artifacts.
[ ] Pre-commit with gitleaks installed BEFORE the first secret exists.
[ ] Full-disk encryption confirmed on the development machine.
[ ] Provider API key stored in the OS keychain, never in a file.
[ ] LICENSE, README, CONTRIBUTING, and compliance policy for source contributions drafted.

---

## Final Note

This document covers all 25 planning dimensions requested. It is based on a complete reading of the 7,163-line PRD.

All architectural decisions are grounded in concrete PRD requirements, risks, or structural observations — not in architectural taste.

**No application code has been written. This document is the deliverable for the planning phase.**

The next step: user approval, then the pre-code checklist, then Phase 0.

The first file to write is src/ajaa/types.py.


---

## AMENDMENTS — Approved with Amendments (2026-09-06)

> The following 8 amendments supersede the corresponding sections above.
> Status changes from "PLANNING" to **"Approved with Amendments — ready for Phase 0"**.

---

### Amendment 1 — candidate_context Semantics

**Original (superseded):** "candidate_context: EXACTLY ONE ROW"

**Corrected:**

```
candidate_context: ONE ROW PER INSTALLATION
```

The correct semantic is:

    One local installation = one active candidate identity

NOT:

    The database schema can only physically hold one candidate

The codebase is a generic open-source tool. Any person can:

    git clone → ajaa init → their own local installation → their own candidate_context row

The DB schema could hold multiple rows. We choose not to expose that surface because
this is not SaaS. The enforcement is:

- ajaa init refuses to create a second row (runtime guard)
- ajaa doctor warns if more than one active row exists
- The bootstrap comment in the migration explicitly says "this is a single-installation
  guarantee, not a schema limitation"

This prevents a future contributor from reading "EXACTLY ONE ROW" and concluding
the architecture is inherently single-user in a bizarre way.

---

### Amendment 2 — Frontend Stack (Remove Alpine.js + Tailwind from MVP)

**Original (superseded):** FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind standalone CLI

**Corrected MVP stack:**

    FastAPI + Jinja2 + HTMX + plain CSS

Rationale:
- Alpine.js: introduces a second reactive model alongside HTMX. Not needed for MVP screens.
- Tailwind standalone CLI: an extra binary to install and run. Plain CSS is sufficient for
  a single-user localhost UI that no designer will review.
- Both can be added later if a specific screen genuinely requires them.

Decision rule: "Add Alpine when you find a specific interaction HTMX cannot express simply.
Add Tailwind if the CSS file exceeds 400 lines and utility classes would shrink it."

No frontend framework creep before Phase 0.

---

### Amendment 3 — SQLAlchemy async vs sync (Add Spike)

**Original (superseded):** "SQLAlchemy 2.0 async + SQLite WAL" as a settled choice.

**Corrected:** This is a Phase 0 spike, not a pre-settled decision.

Spike V-11 (NEW): Compare SQLAlchemy async vs sync for this specific workload.

Considerations:
- Browser automation is already async (Playwright). That does NOT mandate async persistence.
- This is a local-first, single-user tool. The write workload is tens of rows per day.
- Async SQLite with aiosqlite adds complexity (connection pool management, no shared
  in-process state, nested async context management) for no throughput benefit.
- The correct default may be: sync SQLAlchemy for persistence, async only for I/O-bound
  tasks (HTTP calls, browser actions).

Spike V-11 criteria:
1. Can browser automation tasks (async) call sync repository methods without deadlocking?
2. Does aiosqlite add any measurable benefit for this workload?
3. Does mixing sync/async boundaries create complexity that outweighs any benefit?

Default recommendation going into the spike: **sync SQLAlchemy**, unless V-11 reveals a
concrete problem. The async option remains available via the repository pattern.

If sync: use `run_in_executor` for the handful of DB calls inside async browser handlers.
If async: accept the aiosqlite complexity tradeoffs.

Decision recorded after spike. Phase 0 does not proceed past the spike without this answer.

---

### Amendment 4 — Rephrase "SQLite is the queue"

**Original (superseded):** "SQLite is the queue"

**Corrected:**

SQLite persists **job state and scheduling state**. APScheduler is the scheduler.
The DB is durable state storage, not a message queue.

Precise terminology:

    APScheduler   → schedules when pipelines run
    applications table (status column) → durable state of each work item
    locked_by / locked_at columns → claim mechanism (prevents double-processing)
    Lock reaper → releases stale claims after timeout

This is a "state machine in a DB + a scheduler that polls it" pattern,
not a "message queue" pattern. The distinction matters when writing the orchestration code:
there is no enqueue/dequeue API, only state transitions with DB writes.

---

### Amendment 5 — LLM Task/Call-Site Terminology

**Original (superseded):** "exactly 6 LLM call sites" as a fixed architectural constant.

**Corrected:**

Replace "exactly 6 LLM call sites" with "LLM task types defined in tasks.yaml".

The set of tasks is configuration, not a code constant. The current defined set is:

| Task key              | Tier    | Notes                                |
|-----------------------|---------|--------------------------------------|
| cv_extraction         | strong  | once per CV version                  |
| job_requirement_extraction | cheap | cached by description hash          |
| field_classification  | cheap   | batched per page                     |
| question_type_classification | cheap | fallback only, after pattern classifiers |
| match_adjudication    | mid     | ambiguous band only (v0.2)           |
| open_ended_generation | strong  | v0.2                                 |
| recovery_reasoning    | mid     | Tier 2 recovery loop (v0.2)          |
| vision_screenshot     | vision  | v0.3, capped, redacted               |

Adding a new task type = adding an entry to tasks.yaml + a Pydantic schema.
No code change is an architecture change. The document will not become inconsistent
when v0.2 adds recovery_reasoning and vision_screenshot.

The binding constraint remains: no unbounded reasoning, no recursive call sites.

---

### Amendment 6 — Content-Addressed Cache (Not "Permanent")

**Original (superseded):** "same description text extracted exactly once, for life of installation"

**Corrected:**

    same content_hash → same extraction result (cache hit, no LLM call)
    different content_hash → new extraction (cache miss, LLM call)

The cache is content-addressed and immutable per hash. It makes no commitment about
how long entries are retained or whether the policy changes.

Retention policy (separate concern, decided in Phase 4):
- Entries are retained indefinitely by default (they contain no PII, only structured
  requirements extracted from a public job description).
- A background cleanup job can prune entries older than N days if disk space is a concern.
- This is a configurable maintenance parameter, not a semantic commitment.

The phrase "permanently cached" is removed from all architecture documentation.

---

### Amendment 7 — Pre-Submit Job Freshness Check (Hard Gate in PREPARING)

**Original:** freshness check mentioned but not specified as a hard gate.

**Corrected:** Job freshness check is a **hard gate in the PREPARING stage**, not an advisory check.

Before the browser opens for any application, the PREPARING stage MUST verify:

1. Is the job posting still accessible at the stored apply_url?
2. Has the job been removed or redirected to an employer homepage?
3. Has the application deadline passed (if explicit)?
4. Is the employer's ATS still at the expected host?

If any check fails:
- Application transitions to FAILED with reason STALE_JOB
- The job is marked stale in the jobs table
- User is notified via the dashboard

Implementation:
- A lightweight HEAD request to apply_url with a 10s timeout.
- Pattern match on response: 404 / redirect to homepage / "job closed" page → STALE_JOB.
- Freshness TTL: re-check if job was discovered more than 24h ago (configurable).
- A job checked-and-live within the TTL skips the network call (cached freshness signal).

This gate lives in application/planner.py before any LLM work or browser launch.
Cost: one HTTP request per application, amortized by the freshness TTL.

---

### Amendment 8 — Test Targets vs. Phase Acceptance Minimums

**Original:** Phase acceptance criteria included large test counts (~400 unit, ~80 integration, etc.)
as implied gates.

**Corrected:** Distinguish clearly between:

    TEST INVENTORY TARGET (long-term goal, grows over time)
    PHASE ACCEPTANCE MINIMUM (what is required to mark a phase complete)

The numbers (~400 unit, ~80 integration) are **inventory targets** — aspirational totals
for the project at maturity. They are NOT phase gates.

Phase gates are **behavioral**: the specific named tests that verify the phase's acceptance
criteria. A phase is complete when those named tests pass, regardless of total test count.

Updated language for all phases:

> "Phase N is complete when the following named tests pass: [list]"
> NOT: "Phase N is complete when we have N tests"

The genericity suite (4 synthetic candidates) and the adversarial suite (12 cases + 1
false-positive control) ARE phase gates — they must pass before Phase 6 is marked complete.
But 400 unit tests is a project maturity target, not a Phase 1 blocker.

Principle: **quality of coverage over quantity of count**.

---

### Corrected Phase 0 Sequence

Replaces the informal "types.py → everything" progression:

```
Phase 0 — Correct Sequence
│
├── 1. Lock architectural decisions (document ADRs)
├── 2. Run technical spikes (V-01 through V-11, including NEW V-11: sync vs async)
│        → V-01: Provider structured output support
│        → V-03: ATS connector selector stability
│        → V-04: aria_snapshot usability on real forms
│        → V-10: clean-machine bootstrap
│        → V-11: SQLAlchemy sync vs async
│        All spikes produce a written result. Phase 0 does not proceed past this point
│        without spike results recorded.
├── 3. Bootstrap repo: uv init, .gitignore, gitleaks pre-commit, LICENSE
├── 4. Write types.py — Secret, Untrusted[str], enums, sentinels
├── 5. Write minimal config system — Pydantic Settings + YAML loading + startup validation
├── 6. Write security primitives — keyring wrapper, bootstrap guard (data dir outside repo)
├── 7. Write DB foundation — models.py (28 tables), Alembic, SQLite WAL
└── 8. Prove clean install — ajaa init + ajaa doctor on a fresh clone, no source edits
```

No module is written before the spike that validates its foundation.
gitleaks runs before the first secret is created.
Spike results are recorded before any production code is committed.

---

### Confirmed Unchanged Decisions

The following decisions from the original plan are confirmed unmodified:

- CandidateContext as the only handle onto candidate data (enforced by import-graph test)
- Fact Ledger → CanonicalProfile (append-only, precedence-ordered, deterministic projection)
- USER_* facts cannot be superseded by CV_* or LLM_INFERENCE (only CONFLICT)
- Silence in a new CV is NOT deletion (FR-CV-09 invariant)
- Safety ceiling and operational target are permanently separate
- LLM proposes mappings; deterministic code executes browser actions
- UNCERTAIN state is never auto-retried
- calibration_not_completed is a hard gate in never_auto_submit_if
- LinkedIn automation is prohibited in code, with no configuration flag
- all 10 anti-fabrication invariants (I1–I10)
- Genericity suite (4 synthetic candidates) is CI-blocking
- Adversarial suite (12 injection cases + 1 false-positive control) is CI on every commit

---

### v0.1 Scope (Re-confirmed)

v0.1 = Prove the spine:

    CV → Facts → Interview → Profile → Discovery → Match → Greenhouse → Review → Submit → Audit

v0.2 = Automation expansion:

    Lever, Ashby, Generic forms, Email, Free-text answers, Multiple CVs, Auto-selection

---

**Status: Approved with Amendments. Ready to begin Phase 0 after pre-code checklist (Q-BLOCK-06) is completed.**
