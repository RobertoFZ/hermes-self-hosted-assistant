# Severity rubric

Four levels: `blocker` · `major` · `minor` · `nit`.

## What affects the gate

```
APPROVE  ⇔  ( PR author.login != authenticated GitHub login )
            AND ( findings in {correctness, security, migration_safety, test_coverage} == 0  at ANY severity )
            AND ( findings with severity in {blocker, major} == 0  anywhere )
else      →  DO NOT approve
```

So three independent things block approval:

1. A **self-authored PR**. Review it only when the user explicitly targets it or asks to include their own PRs, and publish the result as `COMMENT`; never attempt self-approval.
2. **Any** finding in a critical category (`correctness`, `security`, `migration_safety`, `test_coverage`) — even a `nit`.
3. **Any** `blocker` or `major` finding, in any category.

For PRs authored by someone else, `minor`/`nit` findings in non-critical categories (`architecture`, `error_handling`, `data_layer` non-migration, `scraper`) do **not** block — you approve and leave them inline. On an explicitly requested self-review, the same findings remain non-blocking, but the submission event is still `COMMENT` because of authorship.

## Levels

### blocker
Ships a bug, data loss, security hole, or an outage-class migration. Must not approve.
- Index added on a large/raw table (`TripObservation`, `FareObservation`, `SeatObservation`) without `atomic = False` + `CONCURRENTLY` → write-blocking outage. (see `migration-safety.md`)
- Secret/token committed in code or leaked into a response/log that Bandit didn't catch.
- Provider scoping dropped (`get_queryset` no longer filters `provider`/`deleted_at`) → cross-tenant data leak.
- Correctness bug that corrupts persisted data (e.g. stale `raw_price` used as a discount base, backend PR 3754).

### major
Real bug or significant design break, not necessarily catastrophic, that a user or the pipeline will hit. Must not approve.
- Cross-module contract mismatch that breaks a real flow (template vs upload parser, backend PR 3756).
- Prop mutation during render mutating parent state (web PR 542).
- Timezone bug showing the wrong day (web PR 522).
- Rounding-before-validation submitting invalid data (web PR 547).
- Broad `except Exception` swallowing all errors as `None` on a path that matters (backend PR 3751).
- New visible behavior / new route with zero test coverage (critical category `test_coverage` → blocks regardless).

### minor
Maintainability / clarity issue; correct code, worse design. Approves (unless in a critical category).
- Fat view that should delegate to a service (backend PR 3737).
- Duplicated `Prefetch`/query logic that should be a shared helper (backend PR 3751).
- Oversized component that should be split into smaller components (web).
- Ternary that should be `react-if` (web PR 533).
- Inline callbacks that should be named `useCallback` (web PR 542).
- Reimplementing a primitive instead of reusing `Dialog` (web PR 537).

### nit
Tiny polish; take-it-or-leave-it. Approves (unless in a critical category).
- Redundant condition the helper already guarantees (`if response_parsed:`) (backend PR 3741).
- Intermediate variable for a dense ternax for readability (backend PR 3743).
- Over-`useMemo` on simple derived constants (web PR 526).
- Unused parameter still in a signature (backend PR 3730).

## Note on test/architecture findings

A `test_coverage` finding blocks **even at `nit`/`minor`** because it's a critical category — e.g. "Assert phase contains a data extraction" (AAA violation) or "magic value in assertion" technically blocks approval. In practice score these as `minor` and let the gate do its job: the PR gets `event=COMMENT`, the comment is friendly, and the human fixes it. Architecture findings are *not* critical, so they only block when they rise to `major` (e.g. fragile path-sniffing middleware that will misroute backend URLs, backend PR 3744 — that's a `major` correctness/architecture risk, not a `minor`).
