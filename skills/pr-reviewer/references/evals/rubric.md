# LLM-judge rubric

The judge scores ONE review (the JSON the reviewer emitted) against the fixture diff. It does not re-review; it grades the review. Score each dimension 1–5 (5 best) and return strict JSON.

## Dimensions

1. **decision_correct** — Does `event`/`approved` match the gate for this diff? (APPROVE only if zero critical-category findings AND zero blocker/major.) A wrong decision is an automatic 1.
2. **tone** — Informal `tú` Spanish, friendly, direct. No emoji, no `nit:`/`bloqueante:` prefixes, no character judgments, no motivational filler. English text or formal `usted` caps this at 2.
3. **reason_present** — Each comment states *why* (woven reason / consequence), not just "change this". A bare imperative with no rationale caps at 3.
4. **suggestion_concrete** — Comments include a concrete, correct fix (ideally a snippet) when one applies. Wrong/misleading fixes cap at 2.
5. **severity_correct** — Each finding's `severity` and `category` are sensible (e.g. heavy-table index = blocker/migration_safety; ternary→react-if = minor/architecture).
6. **no_ci_duplication** — No finding duplicates what Ruff/ESLint/Prettier/Black/TypeScript/Bandit/Codacy/CodeRabbit/react-doctor/pytest already catches (formatting, import order, unused vars, type errors, `.po` syntax/format hygiene (but a missing translation for a key the PR *adds* is NOT CI-covered — `compilemessages` compiles empty `msgstr` — so flagging it does not count as duplication), NaN/`??` guards, prop renames like `e`→`event`). Any CI-duplicated finding caps this at 2.
7. **cause_comment** — Top-level comment present **only when not approved AND there is more than one blocking finding**, and then terse (blocking reasons only, no acknowledgments/filler like "gracias"/"buen trabajo"/"no lo apruebo todavía"). Absent when approved or when there is a single blocking finding. Wrong presence/absence, or filler in the comment, caps at 2. (Blocking = critical category at any severity, or `blocker`/`major`.)

## Output format (strict JSON, nothing else)

```json
{
  "decision_correct": 5,
  "tone": 5,
  "reason_present": 5,
  "suggestion_concrete": 5,
  "severity_correct": 5,
  "no_ci_duplication": 5,
  "cause_comment": 5,
  "overall": 5.0,
  "notes": "one short sentence"
}
```

`overall` is the mean of the seven dimensions. Be strict and consistent — the same review must score the same way every time so variance reflects the *reviewer*, not the judge.
