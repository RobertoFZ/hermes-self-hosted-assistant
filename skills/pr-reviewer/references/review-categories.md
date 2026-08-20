# Review categories

Seven categories. Four are **critical** — a finding in any of them blocks approval at *any* severity: `correctness`, `security`, `migration_safety` (lives under `data_layer`), `test_coverage`.

For each finding, ask first: *would Ruff / ESLint / Prettier / Black / TypeScript / Bandit / Codacy / CodeRabbit / react-doctor / pytest already catch this?* If yes, drop it (`ci-already-covered.md`). Only raise what tools can't judge.

---

## 1. correctness / logic *(critical)*

Logic bugs, off-by-one, wrong field semantics, contract mismatches between two sides of a flow, stale/unsynced data.

Real examples from this team:
- **Stale-data persistence bug.** `assign_raw_price()` returns early when `raw_price is not None`, so an existing `TripFare` keeps a stale `raw_price` while `price` already changed → discount computed on a wrong base. (backend PR 3754)
- **Cross-module contract mismatch.** Template auto-filled with historical bus lines that aren't `REVENUE_MANAGEMENT`, but the upload parser only resolves RM bus lines → a downloaded file fails on re-upload. Align both sides of the contract. (backend PR 3756)
- **Cross-submodule contract break.** The PR changes a contract surface (API route, serialized field, request param, enum/status value, auth scope, or event name) that a **sibling repo** consumes — e.g. a backend serializer renames a field the frontend still reads. CI in this repo can't see it. Grep the sibling submodules for the consumer per `cross-repo-impact.md`; a confirmed break the PR (or a coordinated paired PR) doesn't update is `correctness` (blocks). Cite the consumer as `repo/path:line`.
- **Field semantics.** Taking the last `SuggestionActiveHistory` even when the suggestion is no longer active — confirm semantics or return `None`/document it. (backend PR 3755)
- **Frontend: prop mutation during render.** `sort()` mutates a props array during render → mutates parent state. Use a copy: `selectedOriginIds.slice().sort(...)`. (web PR 542)
- **Frontend: timezone bug.** `new Date("yyyy-mm-dd")` parses as UTC; in negative offsets the date picker shows the previous day. Parse as a stable instant (`${value}T12:00:00.000Z`) or a local-date helper. (web PR 522, 547)
- **Frontend: stale derived state.** `initialFilters` computed once and never resynced to `urlFilters` → back/forward leaves stale filters. Listen to `urlFilters` changes and rehydrate. (web PR 522)
- **Frontend: impure state updater.** A `setState` updater that also calls `syncUrlFilters(...)` — updaters must be pure; compute the next draft outside, then call both. (web PR 522)
- **Frontend: rounding-before-validation.** Input rounds `1.5 → 2` before Zod validates, so an invalid value gets submitted instead of rejected. (web PR 547)
- **Frontend: async contract.** Code assumes `onUploadComplete()` returns a Promise (`.catch()`) though the type allows `void`. Use `Promise.resolve(onUploadComplete?.()).catch(...)` or tighten the type. (web PR 550)

## 2. security *(critical)*

Reason about auth/permissions, secrets, injection that Bandit/CodeRabbit miss (they catch obvious hardcoded secrets only). Check:
- Provider scoping: backend `get_queryset()` must filter `provider=self.request.user.provider` and `deleted_at__isnull=True`. A missing provider filter is a data-leak → `major`+.
- Authz logic in views/serializers (serializers must not orchestrate permissions).
- Secrets in code or logs that Bandit didn't flag (e.g. tokens passed through to logging, third-party API keys in responses).
- Raw SQL / `.extra()` / string-built queries → injection surface (ORM usage is normally safe).

## 3. data_layer — N+1, indexes, **migration_safety** *(migration_safety is critical)*

- **N+1 / query strategy.** Query built inside a loop; missing `select_related`/`prefetch_related`; use `Prefetch(..., to_attr=...)` for optimized loads. Store querysets in a variable before mutating (`active = Model.objects.filter(...)`; then `active.update(...)`) — repo style.
- **migration_safety** — see `migration-safety.md`. The blocker: an index on a large/raw table (`TripObservation`, `FareObservation`, `SeatObservation`) without `atomic = False` + `AddIndexConcurrently` / `CREATE INDEX CONCURRENTLY`.
- Backend Django: for `price-engine-python`, load **`backend-django-guidance`**; for `reserhub-intelligence-api`, load its local bootstrap followed by the relevant local **`backend-django-guidance`** and **`backend-db-safety-guidance`** skills. Use these lenses for ORM/DRF/caching/signals/middleware and migration design.

## 4. architecture & CLAUDE.md / AGENTS.md adherence

Convention adherence per each repo's `AGENTS.md` + `docs/agents/`. CI does **not** enforce these.

**Backend (`price-engine-python`, `reserhub-intelligence-api`):**
- Fat view → extract metric/aggregation/business logic to a **service/selector**; keep the view thin (parse request → call service → serialize). (PR 3737)
- Services are stateless: `@staticmethod`/`@classmethod`, return QuerySets/objects, never `Response`.
- DRY duplicated `Prefetch`/query logic into a shared private helper to avoid drift. (PR 3751, 3737)
- One serializer per file, one view per file. `ClassVar` on DRF class attrs. No inline comments — extract to a named method instead.
- Clear type contracts (`QuerySet[Trip]`, not `Model.objects.__class__`). (PR 3737)
- Soft delete everywhere (`deleted_at__isnull=True`).
- **i18n completeness for NEW keys.** When the diff adds a translatable string (`gettext`/`gettext_lazy`/`_(...)`, or a new catalog key under `locale/<lang>/LC_MESSAGES/django.po`), that key must exist in **all three** catalogs (`en_US`, `es_MX`, `pt_BR`) with a **non-empty `msgstr`**. The only CI locale gate is `compilemessages`, which compiles an empty `msgstr` without error — so missing translations ship silently and users see the raw key/fallback. Flag **only keys the PR introduces** (don't surface pre-existing untranslated debt): `minor` by default, `major` if it's prominent user-facing copy in `es_MX`/`pt_BR` (the production locales). Verify by checking the added `msgid` has a filled `msgstr` in each catalog the diff touches.

**Frontend (`reserhub-revenue-web`):**
- **react-if over ternaries.** Replace ternary/nested-ternary conditional rendering with `<If>/<Then>/<Else>` or `<Switch>`. ESLint does not enforce this. (PR 533)
- **Decompose oversized components.** A component concentrating several responsibilities (filters + table + loading state) in one large file → split each block into its own component (`FiltersBar`, `ResultsTable`, …), one responsibility each, easier to test. (named team convention)
- Reuse shared hooks/primitives instead of reimplementing (`useNomenclatureFilters`, `Dialog`/`DialogContent`) — avoid drift. (PR 542, 537)
- Helpers (data transforms) go in a colocated `*Utils.ts`, not inside the hook/component file. (PR 550)
- **Navigation:** `Link` from `@/i18n/navigation` or `NavigationLoaderContext` (programmatic) — not `router.push`, not inline row handlers. (PR 533)
- **Named callbacks** with `useCallback` before the JSX — not inline arrow callbacks in render. (PR 542, 526, 528)
- Don't over-`useMemo` simple derived constants — it adds noise without benefit. (PR 526)
- Use `urlBuilder`/`routeBuilder`, `TableSkeleton` for table loading, `paginationUtils`, `unknown` over `any`.

## 5. test_coverage / adequacy *(critical)*

- **New visible behavior / new route without a focused test** → blocks. Ask for a focused unit/E2E test or an explicit justification per `AGENTS.md`. (web PR 533, 537, 541)
- **AAA — Assert phase only `expect()`.** Data extraction (`response["Location"]`, `workbook.active.title`) belongs in Act, not Assert. (backend PR 3756, 3744; web PR 535)
- **Magic values in assertions** → extract to UPPER_SNAKE_CASE module constants. (backend PR 3756, 3737)
- **Flaky ordering.** `filter(id__in=...)` without `order_by` → Postgres flakes; order explicitly. (backend PR 3755)
- **Test doesn't exercise the asserted path** (e.g. date-filter test passes without seeding in-range data) → false-positive test. (backend PR 3737)
- **Tests coupled to translated copy** for selectors → use stable `data-testid`. (web PR 526, 543)
- Backend uses the `expects` library, factory-boy, function-based tests. Frontend: Vitest unit + Playwright E2E.

## 6. error_handling

- **Broad `except Exception`** that turns any new error into `None`/silent fallback → make expected cases explicit guards, catch only the specific exception. (backend PR 3751)
- Silent failures, swallowed errors, fallbacks that hide real problems, user-facing error messages.

## 7. scraper-specific

For `price-engine-python` scraper/competitor code (`apps/competitors`, `apps/crawlers`, `common/lambdas/scrapers_lambda.py`, `scrapers_swarm_client.py`):
- Proxy / per-country routing correctness (`use_scrapers_swarm` per provider).
- Rate-limit handling and retry/backoff strategy.
- Cost: unbounded fan-out, redundant scrapes, missing batching.
- Fragile path/URL sniffing as routing logic (middleware that guesses URL ownership before Django resolves it is fragile). (backend PR 3744)
