# CI already covers this — do NOT re-flag (the subtract list)

Before raising any finding, check this list. If a tool below already catches it, **drop the finding**. The team relies on these gates and explicitly defers to them ("ignoro el comentario de CodeRabbit según lo acordado").

## Backend — `price-engine-python`

| Tool | Where | Owns (do not re-flag) |
|---|---|---|
| **Ruff** `select=ALL` | pre-commit + Codacy | formatting, line length, import order, unused vars/imports, naming, most docstring rules, bugbear (B), pyupgrade (UP), simplify (SIM), return (RET), perf (PERF), comprehensions, f-strings, async patterns |
| **Ruff-format** | pre-commit | all code formatting |
| **Bandit** | pre-commit + Codacy | obvious hardcoded secrets/passwords, assert-in-prod, unsafe stdlib calls |
| **Codacy** (Pylint, Prospector, Trivy) | CI | complexity/design limits, general code-quality, dependency CVEs |
| **basedpyright** (`ty`) | dev only (NOT CI) | — type hints are NOT gated in CI, so type-contract clarity IS fair game |
| **pytest** (11 shards) | GitHub Actions | test execution / pass-fail (don't predict failures; do review adequacy) |
| **djLint** | pre-commit | Django template formatting |

## Intelligence API — `reserhub-intelligence-api`

| Tool | Owns |
|---|---|
| **Black** (79 cols) | formatting |
| **isort** | import order |
| **Flake8** (+bugbear, comprehensions, simplify) | lint, unused, basic bugs |
| **Pylint** | code quality/design |
| **Bandit** (`-iii -ll`) | high-severity security |

No GitHub Actions test workflow here and no PR-calibration data — lean on the documented conventions plus the Intelligence API's local `backend-django-guidance` and `backend-test-guidance` skills, and be a bit more careful about test adequacy since there's no CI test gate.

## Frontend — `reserhub-revenue-web`

| Tool | Where | Owns (do not re-flag) |
|---|---|---|
| **ESLint** (next/core-web-vitals, next/typescript) | pre-commit (lint-staged) | no-unused-vars, prefer-const, no-var, react-hooks rules, exhaustive-deps, jsx-a11y, jsx-key, no-`<img>`, sort-imports, no-console, no-debugger, no-duplicate-imports |
| **Prettier** | pre-commit | all formatting (quotes, semicolons, trailing commas, width, indent) |
| **TypeScript** `strict` | pre-commit + `next build` | type errors, null checks, implicit any, missing props |
| **react-doctor** | pre-commit hook | React component-quality hints — **defer to it**; optionally run `npx -y react-doctor@0.0.30 <files>` to see its findings, don't duplicate them |
| **Vitest / Playwright** | dev | test execution |

## Frontend admin — `reserhub-revenue-admin`

Same stack and gates as `reserhub-revenue-web` (ESLint next config, Prettier, TypeScript `strict`, react-doctor, Vitest/Playwright) — subtract the same surface. It may not be checked out locally; a cross-repo grep against it can return empty, which is not evidence of "no consumer".

## Scraper service — `scrapers-swarm` (Bun/TypeScript + Prisma)

| Tool | Owns (do not re-flag) |
|---|---|
| **Biome** (`biome.json`) | formatting + lint (the ESLint/Prettier equivalent here) — quotes, semicolons, import order, unused vars, obvious lint |
| **TypeScript** | type errors, null checks, implicit any |
| **Prisma** | schema validation / generated client types |

What's LEFT for you here: TS runtime/logic correctness, the swarm request/response **contract**, Prisma query strategy & **migration safety**, and the scraper concerns in category 7 (proxy/country routing, rate limits, retry/backoff, cost/fan-out).

## CodeRabbit (bot) — heavily relied on across both repos, subtract its surface

Humans here let CodeRabbit own these, so you should too:
- Type-hint mismatches (`datetime.date | None` vs `str | None`), docstring completeness, `help_text`, OpenAPI response-code documentation.
- **i18n / `.po` syntax & format** — malformed entries, `fuzzy` markers, singular/plural drift across `en_US`/`es_MX`/`pt_BR`. CodeRabbit owns format/drift, and the backend CI `compilemessages` job catches *syntax* errors. Don't hunt pre-existing `.po` debt. **Caveat:** `compilemessages` compiles an empty `msgstr` without error, so it does **not** catch missing translations — a NEW key the PR introduces with an empty/missing `msgstr` in `es_MX`/`pt_BR` ships the raw key to users and IS fair game (see `review-categories.md` backend i18n bullet). Localized *copy in the wrong language inside a catalog* — e.g. an English breadcrumb in the Spanish bundle — is also fair game as a `minor`.
- `$NaN` / parse-failure guards, `||` vs `??` zero-value bugs, double-space formatting-helper misuse.
- Library/prop API compatibility (e.g. invalid flowbite-react props) — CodeRabbit web-verifies these.
- Whitespace-only-string normalization (`strip()`).

## What's LEFT for you (CI blind spots — your whole job)

Logic correctness · design/architecture & AGENTS.md adherence (fat-view→service, component decomposition, react-if, Link, reuse) · N+1 / query strategy · **migration safety** · test adequacy (AAA, magic values, flaky ordering, missing coverage for new behavior, tests that don't exercise the path) · security reasoning (authz, provider scoping, leaks) · error handling (broad except, silent failures) · scraper proxy/rate/cost. Type-contract clarity is also fair game (basedpyright isn't in CI). **i18n completeness for keys the PR adds** is fair game too — `compilemessages` only validates syntax, not whether new `msgstr` entries are filled.
