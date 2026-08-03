# AI Suitability Copilot 🧭

**An AI-native compliance workflow where the model recommends and a deterministic policy decides.**

Financial suitability assessments are a cornerstone of regulatory compliance, but
they traditionally trap human expertise in a high-volume, low-leverage workflow.
Highly trained compliance officers spend hours manually reviewing standard
"obviously suitable" profiles, leaving less time for complex edge cases.

This service redesigns that back-office workflow from a *manual assembly line*
into an *exception-handling and oversight* system. The model reads the profile.
A deterministic policy engine makes the call. Every step is auditable, and the
model is structurally incapable of rejecting a client on its own.

> Built as a take-home exercise for the **AI Builder** role at **Wealthsimple**.
> The original brief and my written answers are in
> [`docs/take-home-brief.md`](docs/take-home-brief.md).

---

## Quickstart

```bash
git clone <this-repo> && cd suitability-copilot
docker compose up --build
```

That's it. No `.env`, no API key, no manual migration step. The stack comes up
with Postgres, Redis, an API, and a Celery worker, runs its migrations, and
serves on **http://localhost:8000** (interactive docs at `/docs`).

With no `OPENAI_API_KEY` configured, the pipeline runs on a **deterministic stub
reviewer** so the full human-in-the-loop flow is demonstrable offline. Reviews it
produces are stamped `model_version="stub-v1"`, so stub output is never confused
with model output in the audit trail or the drift metrics.

To use the real model, add a key — nothing else changes:

```bash
cp .env.example .env
# set OPENAI_API_KEY=sk-...
docker compose up --build
```

---

## Try it

**1. Create an account.** Returns immediately; the review runs in the background.

```bash
curl -sX POST localhost:8000/accounts -H 'content-type: application/json' -d '{
  "age": 34, "income": 90000, "net_worth": 120000,
  "risk_tolerance": "High", "investment_choice": "Growth equities",
  "investment_horizon": 20, "notes": "Experienced investor"
}'
# → {"account_id":"...","review_id":"...","status":"PENDING"}
```

**2. Poll the review.** `PENDING` → `COMPLETED`.

```bash
curl -s localhost:8000/reviews/<review_id>
# → "ai_decision":"APPROVE", "effective_decision":"AUTO_APPROVED", "confidence":0.95
```

**3. Watch the guardrail fire.** This profile is internally contradictory — low
risk tolerance against a growth product:

```bash
curl -sX POST localhost:8000/accounts -H 'content-type: application/json' -d '{
  "age": 68, "income": 40000, "net_worth": 55000,
  "risk_tolerance": "Low", "investment_choice": "High-growth equities",
  "investment_horizon": 2, "notes": "Wants fast gains"
}'
# → the review completes as effective_decision: "ESCALATED"
```

**4. Override as a human.** The AI's reasoning is preserved; the override is
logged separately.

```bash
curl -sX POST localhost:8000/reviews/<review_id>/override \
  -H 'content-type: application/json' \
  -d '{"new_decision":"AUTO_APPROVED","reason":"Client confirmed understanding by phone"}'
```

**5. Inspect the queue and the vitals.**

```bash
curl -s "localhost:8000/reviews?decision=ESCALATED"
curl -s localhost:8000/metrics
```

---

## How it works

```
POST /accounts
      │
      ├─► Account + Review(PENDING) + ACCOUNT_CREATED audit ── one transaction ──► Postgres
      │
      └─► enqueue ──► Redis ──► Celery worker
                                      │
                                      ├─ 1. Provider evaluates profile ──► strict JSON schema
                                      │      (OpenAI gpt-4o, or stub-v1 offline)
                                      │      any failure ⇒ fail-safe: confidence 0.0, ESCALATE
                                      │
                                      ├─ 2. policy_engine.apply_policy()
                                      │      BLOCK                      ─► ESCALATED
                                      │      APPROVE & confidence ≥0.90 ─► AUTO_APPROVED
                                      │      everything else            ─► ESCALATED
                                      │
                                      └─ 3. Review update + AI_EVALUATED + POLICY_APPLIED
                                            ──── one transaction ────► Postgres
```

### The three ideas worth reading the code for

**AI suggests, policy decides.** `app/services/policy_engine.py` is 26 lines of
pure, deterministic branching with no model in the loop. Even a `BLOCK` at 99%
confidence becomes `ESCALATED`. The model can never reject a client — a false
rejection is a far worse outcome than a human reading one more file.

**The fail-safe cannot be bypassed.** `LLMService.evaluate()` always returns a
valid result: on timeout, malformed JSON, schema violation, or provider crash it
returns `confidence=0.0, decision=ESCALATE`, which the policy engine can only
route to a human. The fail-safe lives in the facade rather than in providers, so
adding a provider cannot introduce a path around it.

**If you can't audit it, you don't process it.** `app/services/audit_service.py`
deliberately does *not* commit — the caller owns the transaction. An audit write
failure rolls back the decision it was describing. A `COMPLETED` review without
its `AI_EVALUATED` and `POLICY_APPLIED` rows is not a state this system can
reach.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/accounts` | Create an account, queue a review, return immediately |
| `POST` | `/accounts/{id}/review` | Trigger a review (idempotent — returns any existing PENDING/COMPLETED review) |
| `GET` | `/reviews/{id}` | Poll status and read the full assessment |
| `GET` | `/reviews?decision=&status=` | The human reviewer's work queue |
| `POST` | `/reviews/{id}/override` | Human override; preserves AI reasoning |
| `GET` | `/metrics` | Pipeline counters (approval / escalation / override / failure rates) |
| `GET` | `/health` | Liveness — process is up |
| `GET` | `/ready` | Readiness — Postgres and Redis reachable |

---

## Configuration

Every setting has a working default. `.env` is optional; see
[`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto` \| `openai` \| `stub`. `auto` uses OpenAI when a key exists, else the stub |
| `OPENAI_API_KEY` | *(empty)* | Set to use the live model |
| `OPENAI_MODEL` | `gpt-4o` | Model id, stamped onto every review it decides |
| `POSTGRES_USER` / `_PASSWORD` / `_DB` | `postgres` / `postgres` / `copilot` | Provisions Postgres and builds `DATABASE_URL` |
| `LOG_LEVEL` | `INFO` | Application log level |

---

## Tests

The suite runs fully offline against the stub reviewer — no credentials, no
network:

```bash
docker compose run --rm api pytest -v
```

51 tests covering schema validation, every policy-engine branch, audit-trail
integrity, human override, admin filtering, the full async lifecycle, and
operator metrics.

`tests/test_metrics.py` is worth a look: it writes reviews straight to the
database rather than through the API, because the suite runs Celery eagerly and
a test that went through the API would pass even if metrics were process-local
again — which is exactly how that bug survived unnoticed the first time.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the suite
against a real Postgres, audits pinned dependencies for CVEs with `pip-audit`,
and asserts that no `.env` was baked into the Docker image.

For live-reload development:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Reset all state (including the Postgres volume): `docker compose down -v`.

---

## Security scope & known gaps

This is a portfolio prototype, and the boundary is drawn deliberately rather
than accidentally.

**Addressed.** Non-root container on a slim base; `.dockerignore` keeps secrets
and VCS history out of image layers; pinned dependencies with CVE auditing in
CI; readiness probe reports check status without leaking driver errors (which
routinely embed connection credentials); Redis is not published to the host and
Postgres is bound to loopback only; no credentials are committed, and none ever
entered the git history.

**Deliberately out of scope — this is what production would need first:**

- **No authentication or authorization.** `POST /reviews/{id}/override`,
  `GET /reviews`, and `GET /metrics` are unauthenticated. Consequently the
  `actor` recorded on `HUMAN_OVERRIDE` audit rows is the placeholder
  `"admin_user"` rather than a real identity. For a system whose entire premise
  is accountable human oversight, authenticating the reviewer and recording who
  they were is the first thing to build next.
- **No rate limiting** on account creation.
- **No PII handling policy.** Account profiles are stored in plaintext and sent
  to the model provider; a real deployment needs a data-residency and retention
  position.
- **Metrics are aggregate queries, not a time series.** `/metrics` recomputes
  from the reviews table on every call. That is correct and restart-safe, but it
  has no time dimension and will not stay cheap as the table grows — real drift
  monitoring needs a proper time-series store. See
  [`docs/model_versioning_strategy.md`](docs/model_versioning_strategy.md).

---

## Further reading

- [`docs/take-home-brief.md`](docs/take-home-brief.md) — the original exercise and my answers: what the human can now do, what the AI owns, where it must stop, and what breaks first at scale.
- [`docs/model_versioning_strategy.md`](docs/model_versioning_strategy.md) — how `model_version` is tracked per review, how drift is detected, and the regression sampling plan for promoting a new model.

## Stack

FastAPI · PostgreSQL · SQLAlchemy · Alembic · Celery · Redis · OpenAI · Docker Compose · pytest
