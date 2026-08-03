# Origin: Wealthsimple AI Builder Take-Home

This project was built as a take-home exercise for the **AI Builder** role at
**Wealthsimple**. The brief was not "build a feature" — it was to design an
AI-native business process and defend the boundary between what the model does
and what a human must keep doing.

That framing is why the repository looks the way it does: the interesting part
is not the model call, it's the deterministic policy layer wrapped around it,
the audit trail that makes every decision reconstructable, and the explicit
refusal to let the model reject anyone on its own.

The four questions below were part of the brief, with a 500-word limit across
all answers. They are reproduced here as submitted, with technical details
corrected where the implementation has since changed.

---

## 1. What the human can now do that they couldn't before

Instead of manually reading and rubber-stamping every newly opened account (the
vast majority of which are perfectly suitable), human operators now act as
**exception handlers and fleet managers**.

Humans dedicate 100% of their cognitive load to the ~10% of cases that are
highly complex, ambiguous, or regulatory red flags. Furthermore, they move from
operating the mechanical crank to monitoring the system's performance, using
observability (like auto-approval ratios vs. override ratios) to identify
behavioral drift in the model over time.

## 2. What AI is responsible for

The AI is responsible for **semantic reasoning and feature extraction at
scale**. It analyzes semi-structured client profiles (age, net worth, risk
tolerance, free-text notes) against financial suitability principles. It must
compress this analysis into a strict schema, emitting a recommendation, a
confidence score, and explainable reasoning for its findings.

## 3. Where AI must stop (the critical human decision)

**The AI never makes the final operational decision.**

The critical decision that must remain human is **handling rejections and
uncertainty**. In `app/services/policy_engine.py`, even if the AI recommends
`BLOCK` with 99% confidence, the policy forces an `ESCALATE` status. The AI is
explicitly banned from autonomously rejecting a client or handling ambiguous
"edge" profiles. False positives in rejections create terrible client
experiences; therefore, final negative friction or resolving uncertainty is the
exclusive domain of human judgment.

## 4. What would break first at scale

1. **Asynchronous queue saturation.** Concurrency against the model provider is
   bounded by Celery worker concurrency and a prefetch multiplier of 1. A sudden
   spike in account openings would back up the Redis queue. This would need
   horizontal pod autoscaling for the workers, driven by queue depth.
2. **Context latency & fail-safes.** The provider call has a hard 10-second
   timeout. If the provider degrades, the fail-safe triggers and escalates
   *everything* to the human queue. The human team would rapidly be overwhelmed
   by the fallback volume, requiring a circuit breaker or a fallback model.
3. **Stateful metrics.** As submitted, `/metrics` used in-memory threading
   counters, which wipe on pod restart. At scale this must move to a real
   time-series store (Prometheus/Datadog) to reliably track operational drift.

   *Correction since submission:* those counters were worse than described.
   Once the pipeline moved to Celery, the worker incremented counters in its own
   process while `/metrics` was served by the API process, so every pipeline
   counter read as zero regardless of throughput. They are now derived from the
   reviews table, which is correct across processes and survives restarts. The
   scaling point still stands, for a different reason: aggregate queries have no
   time dimension and degrade as the table grows.

---

## What changed after the submission

The repository has since been hardened for public use. Behaviour relevant to the
answers above is unchanged — the policy engine, the fail-safe, and the audit
contract are exactly as submitted. The changes were:

- A provider abstraction so the pipeline runs offline on a deterministic
  reviewer when no API key is present (see [`../README.md`](../README.md#configuration)).
- Reproducible, one-command startup: pinned dependencies, healthcheck-gated
  service ordering, and a one-shot migration job.
- Container hardening: non-root user, slim base image, `.dockerignore`.
- Bug fixes found on re-read — see the repository history for detail.
