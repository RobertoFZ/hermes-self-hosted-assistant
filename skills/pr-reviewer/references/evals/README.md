# pr-reviewer evals

Five golden fixtures derived from real Reserhub PR patterns:

- `01-clean-approvable` — typed stateless service + AAA `expects` test, nothing critical → must `APPROVE`.
- `02-planted-blocker` — inverts the real safe migration `0211_busline_seat_type_index.py` into an in-transaction `AddIndex` on `TripObservation` (~2.08B rows) → must **not** approve, `event=COMMENT`, top-level cause naming the migration.
- `03-mixed-minor` — maintainability nits only (ternary→react-if, inline callback) → `APPROVE` with inline comments.
- `04-multi-blocker` — provider scoping and missing endpoint coverage → must not approve and must include a terse multi-cause summary.
- `05-partial-failure-retry` — a status is persisted before a later side effect, so failure leaves the item outside future retries and lacks failure-path coverage → must not approve.

Each fixture = `pr.json` (metadata + provenance), `diff.patch` (the diff under review), `expected.json` (gate expectations).

## Run

```bash
# default reviewer/judge = ephemeral `codex exec` reading stdin
python3 scripts/eval.py                      # all fixtures, five runs each
python3 scripts/eval.py --no-judge           # deterministic + variance only
python3 scripts/eval.py --fixture 02-planted-blocker --runs 5
REVIEWER_CMD="my-runner" JUDGE_CMD="my-runner" python3 scripts/eval.py
```

`REVIEWER_CMD`/`JUDGE_CMD` (or `--reviewer-cmd`/`--judge-cmd`) must name a CLI that reads a prompt on **stdin** and writes the model response to **stdout**. The harness inlines `SKILL.md` + all `references/` into the reviewer prompt, so it tests the skill content directly regardless of install location.

## Layers

1. **Deterministic** — correct `event`/`approved` per the gate; gate self-consistency (no APPROVE with a critical-category or blocker/major finding); **no merge call ever** (raw output scanned for `gh pr merge` & friends); comments look Spanish; no severity-prefix; valid severity/category tags; top-level cause iff not approved; expected critical categories present/absent; comment-count bounds.
2. **LLM-judge** — `rubric.md`: tone, reason-present, concrete suggestion, severity correct, no CI-duplicated findings, cause comment. Returns per-dimension 1–5 + `overall`.
3. **Variance** — N≥5 runs per fixture; reports decision stability and judge-score variance. **A decision flip across runs fails the harness** (gate-reliability bug).

Exit code is non-zero if any deterministic assertion fails or any decision flips.
