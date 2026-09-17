# Severity rubric

Four levels: `blocker` · `major` · `minor` · `nit`.

## What affects the gate

```
APPROVE  ⇔  ( PR author.login != authenticated GitHub login )
            AND ( findings in {correctness, security, migration_safety, test_coverage} == 0  at ANY severity )
            AND ( findings with severity in {blocker, major} == 0  anywhere )
else      →  DO NOT approve
```

So three independent things block an approval proposal:

1. A **self-authored PR**. Analyze it only when the user explicitly targets it or asks to include their own PRs, and propose `COMMENT`; never attempt self-approval.
2. **Any** finding in a critical category (`correctness`, `security`, `migration_safety`, `test_coverage`) — even a `nit`.
3. **Any** `blocker` or `major` finding, in any category.

For PRs authored by someone else, `minor`/`nit` findings in non-critical categories (`architecture`, `error_handling`, `data_layer` non-migration, `scraper`) do **not** block an approval proposal. On an explicitly requested self-review, the same findings remain non-blocking, but the proposed event is still `COMMENT` because of authorship. `blocking` is derived from this gate; do not use it to inflate a preference into a risk.

## Materiality boundary

A candidate must identify a plausible, evidence-backed risk to at least one of:

- runtime behavior or correctness;
- security or authorization;
- persistent data integrity or query behavior;
- migration safety;
- rollout compatibility across deployed versions or repositories; or
- meaningful regression coverage for changed behavior or a failure path.

Withhold convention-only feedback even when a repository guide prefers it. In particular, do not create candidates for test assertion placement, assertion constants, extracting a one-use helper, or a speculative abstraction that has no demonstrated failure or drift risk. Do not turn “could be cleaner” or “might be reusable later” into an architecture finding. Missing coverage is material only when you can name the changed behavior, boundary, invariant, or failure mode that could regress undetected.

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
A localized but evidence-backed defect or regression risk with limited blast radius. It can propose approval only when its category is non-critical.
- A retry path loses a specific error signal but has a bounded fallback.
- A query pattern demonstrably adds repeated database work on a bounded path.
- Rollout compatibility is unclear for one mixed-version edge, with evidence from the changed contract.

### nit
The lowest material risk: concrete and worth the author's attention, but narrowly scoped. Do not use `nit` for polish, naming, formatting, a one-use helper, or speculative refactoring; withhold those entirely. A `nit` in a critical category still blocks under the gate, so confirm that the risk is real before retaining it.

## Test and architecture findings

A `test_coverage` finding blocks even at `nit`/`minor`, which is why mechanical test preferences must never enter the proposal. Assertion placement and assertion constants are not findings. Retain missing coverage only for a material changed behavior or failure path, and name that risk in the evidence.

Architecture findings are not critical, but they still cross the materiality boundary. A current fragile path-sniffing middleware that demonstrably misroutes backend URLs is material; a speculative abstraction, class extraction, or one-use helper preference is not.
