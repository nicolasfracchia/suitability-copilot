# Model Versioning Strategy

## Overview

This document defines how the AI model version is tracked per review, how behavioral drift is detected, and the sampling plan for regression testing when a new model version is deployed.

---

## 1. How `model_version` Is Stored

Every review record in the `reviews` table includes a `model_version` column (`VARCHAR(50)`).

- **Set at evaluation time**: The value is sourced from the `MODEL_VERSION` constant defined at the top of `app/services/llm_service.py`:
  ```python
  MODEL_VERSION = "gpt-4o"
  ```
- **Immutable per review**: Once a review is written to the DB, its `model_version` is never updated, even if the service is upgraded. This gives a permanent record of which model produced which decision.
- **Promoted via deployment**: To upgrade models, update the constant and redeploy. All reviews created after the deployment will carry the new version string.

### Querying by Version

```sql
-- Compare decision distributions across model versions
SELECT model_version, effective_decision, COUNT(*) as count
FROM reviews
WHERE status = 'COMPLETED'
GROUP BY model_version, effective_decision
ORDER BY model_version, effective_decision;
```

---

## 2. How Drift Is Monitored

### Short-term (In-Memory Metrics)

Exposed via `GET /metrics`, the counters track aggregate pipeline behavior:

| Counter | What it signals |
|---|---|
| `total_reviews` | Overall throughput |
| `auto_approved` | Auto-approval rate |
| `escalated` | Escalation rate |
| `llm_failures` | Fail-safe escalations (model errors) |
| `overridden` | Human correction rate |

A sudden shift in `auto_approved` vs `escalated` ratios after a model update is a primary drift signal.

### Long-term (Database Aggregation)

Run the SQL query above periodically (e.g., in a scheduled job or a data dashboard) to compare:
- **Approval rate** per model version.
- **Escalation rate** per model version.
- **Average `suitability_score`** per model version.

A statistically significant shift in any of these metrics between `model_version` values indicates potential behavioral drift.

---

## 3. Sampling & Regression Test Plan

When a new model version is considered for deployment, the following process must be followed.

### Step 1: Assemble a Canonical Profile Set

Maintain a file `tests/fixtures/regression_profiles.json` containing **at least 20 diverse account profiles** with known expected outputs:
- 5 clearly suitable profiles → expected `APPROVE` / `AUTO_APPROVED`
- 5 clearly unsuitable profiles → expected `ESCALATE`
- 5 borderline profiles → expected behavior documented
- 5 edge cases (extreme age, zero income, etc.)

### Step 2: Run Regression Suite Against New Model

A test script (or pytest module `tests/test_model_regression.py`) calls the real `LLMService.evaluate()` with the new model and compares:
- Whether the `decision` (APPROVE/ESCALATE/BLOCK) matches the expected value.
- Whether the `confidence` is within acceptable variance (+/- 0.15 of the baseline).

**Pass criteria**: ≥ 90% agreement with the canonical profile set.

### Step 3: Compare Against Production Baseline

Before promoting, run a shadow deployment on 5–10% of live traffic (or a sample of recent reviews), storing results in a separate `review_shadow` table. Compare `effective_decision` distributions with `chi-square test` or a simple ratio check.

### Step 4: Document on Deploy

When promoting a new `MODEL_VERSION`:
1. Update the constant in `llm_service.py`.
2. Add an entry to `CHANGELOG.md` with version string, date, and reason.
3. Archive baseline regression results.

---

## 4. Alert Thresholds (Recommended)

| Metric | Alert if... |
|---|---|
| Auto-approval rate | Shifts by > 15% vs 7-day rolling average |
| LLM failure rate | Exceeds 5% of total reviews |
| Human override rate | Exceeds 10% of completed reviews |
| Avg suitability score | Shifts by > 10 points between model versions |
