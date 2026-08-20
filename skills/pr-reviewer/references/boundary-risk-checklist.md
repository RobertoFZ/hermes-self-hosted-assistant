# Boundary-risk checklist

Apply this pass before reviewing files independently. Most CI-blind regressions
cross a boundary: an identity reaches persistence, a state transition fails
halfway, a scope broadens from one entity to many, or a consumer observes only
part of an update.

## Contents

- Build the behavior map
- Challenge identity, failure, scope, async, UI, and test invariants
- Escalate the review for large branches

## 1. Build the behavior map

For every changed behavior, write a compact map:

`input → validation → state transition → persisted identity → output/event → consumer`

Record these dimensions when relevant:

- provider/tenant, route, trip, sale channel, date/time, locale;
- zero, one, and many entities;
- first attempt, retry, rollback, and concurrent execution;
- legacy/empty/optional input and the new representation;
- external calls, queues, callbacks, caches, and UI URL state.

Trace both the happy path and at least one failure after the first side effect.
Use the map to locate code and tests; do not publish the map unless it helps
explain a finding.

## 2. Challenge the invariants

### Identity and contract

- Confirm the identifier used for an upsert/cache key remains unique for every
  variant the producer can emit.
- Separate grouping identity from persistence identity when two records may
  represent one physical trip but distinct classes/channels/configurations.
- For required/renamed fields, test the existing empty or legacy form before
  treating the new representation as mandatory.
- Trace producer and consumer together for serialized fields, update payloads,
  enums, URL params, and async events.

### Atomicity and retryability

- Find the first persistent write. If a later operation fails, prove rollback
  or a durable retry path restores consistency.
- Check that a failed item remains selectable by the next run; a status flipped
  before failure must not exclude it from retries.
- For per-item isolation, confirm one failure cannot overwrite the outcome of
  sibling items.
- Check concurrency with locking, idempotency, or versioning where two workers
  may process the same state.

### Cardinality and scope

- Replace "the first item represents all items" assumptions with the complete
  set of providers, channels, routes, trips, or contexts.
- Add a two-entity counterexample: two providers, two channels, two trips, or
  two variants with different outcomes.
- Verify filters and writes use the target item's scope, not the original group
  context.

### Async and external failures

- Treat enqueue/broker success, ordering, duplication, and delayed execution as
  independent from database commit success.
- Verify callbacks do not propagate an external failure after the domain change
  has committed unless that is an intentional contract.
- Check stale or out-of-order events and bound fan-out/concurrency.
- Ensure command/scheduler exit status exposes partial failures.

### UI and URL boundaries

- Test deep links independently from list-page success. A list error must not
  hide a detail modal that has its own request/error state.
- Ensure mutation responses or refetches update every displayed derived field,
  including channel/provider-specific state.
- Check empty, loading, partial-error, retry, close/reopen, back/forward, and
  stale-response behavior.

### Tests and evidence

- Prefer counterexample tests that target the invariant above, not only the
  happy path.
- Treat a pass only after retry as flaky; require the first attempt to be
  deterministic.
- Avoid one-shot visibility/readiness probes immediately after async state
  changes.
- Verify tests exercise the asserted branch, including unreachable error paths
  and direct configuration/secret propagation.
- Keep OpenSpec tasks and PR claims aligned with evidence actually produced on
  the reviewed head.

## 3. Escalate the review for large branches

The repository guideline is under 20 files and around 500 changed lines.

When either threshold is exceeded:

1. Report the size risk separately from code findings.
2. Partition the diff into behavioral slices and review each slice through the
   full behavior map.
3. Run a final integration pass across the slices for shared contracts and
   state.
4. Recommend splitting before PR creation when the slices can merge
   independently. Do not make size alone a blocking finding when the branch
   cannot be split safely.
