# AI Suitability Copilot 🧭

*[Built for the Wealthsimple AI Builder Role]*

Financial suitability assessments are a cornerstone of regulatory compliance, but they traditionally trap human expertise in a high-volume, low-leverage workflow. Highly trained compliance officers spend hours manually reviewing standard "obviously suitable" profiles, leaving less time for complex edge cases.

**AI Suitability Copilot** is a prototype of an AI-native business process designed to meaningfully expand what a human can do. It redesigns the back-office compliance workflow from a *manual assembly line* into an *exception-handling and oversight* system.

---

## 🏗 System Architecture & Flow

The system is built as a production-grade, asynchronous service using **FastAPI**, **PostgreSQL** (with Alembic for migrations), **Redis**, and **Celery**.

### The Review Lifecycle

1. **Intake (FastAPI):** An account is created. The `/accounts` endpoint immediately commits the account and queues an idempotent, asynchronous review task.
2. **Evaluation (Async LLM):** A Celery task securely calls an LLM (`gpt-4o`) to evaluate the client's profile. The AI is strictly instructed to return a structured JSON assessment containing a `suitability_score`, `confidence`, a recommended `decision` (`APPROVE`, `ESCALATE`, `BLOCK`), and human-readable reasoning.
3. **Deterministic Policy (The Guardrail):** **AI suggests, policy decides.** The raw LLM output is passed to a deterministic `policy_engine`. If the AI recommends `APPROVE` with `>90%` confidence, it is `AUTO_APPROVED`. Anything else—including all `BLOCK` recommendations or any LLM failure/timeout—is `ESCALATED`.
4. **Immutable Audit (PostgreSQL):** Every step of the process is logged in an append-only `audit_logs` table. If it cannot be audited, the transaction rolls back. 
5. **Human Override:** Through a dedicated endpoint `/reviews/{id}/override`, humans can manually override the final decision while preserving the original AI reasoning and logging the exact human actor in the audit trail.

---

## 📝 The Wealthsimple Prompt Answers

*(Max 500 words)*

### 1. What the human can now do that they couldn't before
Instead of manually reading and rubber-stamping every newly opened account (the vast majority of which are perfectly suitable), human operators now act as **exception handlers and fleet managers**. 

Humans dedicate 100% of their cognitive load to the ~10% of cases that are highly complex, ambiguous, or regulatory red flags. Furthermore, they move from operating the mechanical crank to monitoring the system's performance, using observability (like auto-approval ratios vs. override ratios) to identify behavioral drift in the model over time.

### 2. What AI is responsible for
The AI is responsible for **semantic reasoning and feature extraction at scale**. It analyzes semi-structured client profiles (age, net worth, risk tolerance, free-text notes) against financial suitability principles. It must compress this analysis into a strict schema, emitting a recommendation, a confidence score, and explainable reasoning for its findings. 

### 3. Where AI must stop (The Critical Human Decision)
**The AI never makes the final operational decision.** 

The critical decision that must remain human is **handling rejections and uncertainty**. In this system's `policy_engine.py`, even if the AI recommends `BLOCK` with 99% confidence, the policy forces an `ESCALATE` status. The AI is explicitly banned from autonomously rejecting a client or handling ambiguous "edge" profiles. False positives in rejections create terrible client experiences; therefore, final negative friction or resolving uncertainty is the exclusive domain of human judgment.

### 4. What would break first at scale
1. **Asynchronous Queue Saturation:** The Celery worker limits LLM concurrency via a semaphore to avoid rate limits. A sudden massive spike in account openings would back up the Redis queue. We would need horizontal pod autoscaling for the workers based on queue depth.
2. **Context Latency & Fail-safes:** The LLM call has a hard-coded 10-second timeout. If OpenAI degrades, the fail-safe triggers, escalating *everything* to the human queue. The human team would rapidly be overwhelmed by the fallback volume, requiring a circuit breaker or fallback models.
3. **Stateful Metrics:** The current `/metrics` endpoint uses simple in-memory threading counters. If the Kubernetes pods restart, the counters wipe. At scale, this must be migrated to a real time-series database (e.g., Prometheus/Datadog) to reliably track operational drift.

---

## 🛠 Running the System Locally

**Prerequisites:** Docker, Docker Compose.

1. Clone the repository and add your `.env` file containing your `OPENAI_API_KEY`. (See `.env.example`).
2. Run `docker-compose up --build -d`
3. The API will be available at `http://localhost:8000`
4. The system automatically runs all Alembic migrations on startup.

### Key Endpoints
- `POST /accounts`: Create an account and trigger background review.
- `GET /reviews/{id}`: Poll for the review status (`PENDING` -> `COMPLETED`).
- `POST /reviews/{id}/override`: Human override of an escalated review.
- `GET /metrics`: Observe the system's vital stats.
- `GET /health` & `GET /ready`: Production readiness probes. 

### Tests
To run the comprehensive integration and unit test suite:
```bash
pytest tests/ -v
```
*(The suite includes a full end-to-end integration flow mimicking the Postgres/LLM/Policy lifecycle without hitting the real OpenAI API).*
