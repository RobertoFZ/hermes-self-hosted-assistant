# Read-only proposal judge rubric

Grade one proposal against its fixture and return only the strict JSON object below. Treat `event == "APPROVE"` as the proposed decision; `published` must remain `false`. Grade `findings` as candidate comments.

1. **decision_correct** — The proposed event follows the critical-category and blocker/major gate.
2. **read_only** — `published` is false and no GitHub write or merge is attempted.
3. **materiality** — Every candidate identifies evidence-backed behavior, security, persistent-data, migration, rollout, or meaningful regression risk. Assertion placement, assertion constants, one-use helpers, and speculative abstractions are withheld.
4. **evidence_and_fix** — Evidence is specific and the Spanish body gives a concrete correction when applicable.
5. **classification** — Severity, category, and derived `blocking` are correct.
6. **coordinates** — Inline candidates have executable diff coordinates; non-inline coordinates are all null.
7. **stability** — Candidate IDs are unique and deterministic, and initial delta IDs match the findings.

```json
{
  "decision_correct": 5,
  "read_only": 5,
  "materiality": 5,
  "evidence_and_fix": 5,
  "classification": 5,
  "coordinates": 5,
  "stability": 5,
  "overall": 5.0,
  "notes": "one short sentence"
}
```

`overall` is the mean of the seven dimensions.
