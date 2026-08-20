# Cross-submodule impact

A PR lives in one repo, but its diff can break code in a **sibling submodule** — the classic case: the backend changes an endpoint's contract and the frontend that calls it still expects the old shape. CI in the PR's own repo can't see this: the backend's tests pass, the frontend's tests aren't in this PR, and no tool reads across the two repos. This is your job, and it lands in `correctness` (critical).

This reference tells you (1) what to treat as a **contract surface**, (2) how to find its **consumers** in the other submodules, and (3) how to **classify** what you find.

## Where the other repos live

Resolve the monorepo with `scripts/prepare-workspace.sh --fetch` as described in
`references/workspace.md`. Its `MONOREPO_ROOT` contains all submodules side by
side:

```
price-engine-python/        # backend Django (producer of most contracts)
reserhub-intelligence-api/  # Django AI/analytics (both producer and consumer)
reserhub-revenue-web/       # frontend Next.js/React (consumer)
reserhub-revenue-admin/     # frontend admin (consumer)
scrapers-swarm/             # scraper service (producer/consumer of the swarm contract)
```

All consumer inspection is **read-only**: use `git grep` against the fetched
remote ref reported by the workspace script. You answer *"does anything here
rely on what this PR changed?"* without checking out the PR's branch and without
a worktree. The producer side comes from `gh pr diff`. But **which state** of
the consumer you search matters—the wrong state produces false "breaks".

## Step 0 — which state do the consumers live in? (base branch matters)

Before grepping, read the PR's **`baseRefName`**. It decides where the real consumer lives:

- **Base is the repo mainline (`develop`/`main`/`master`)** — the normal case. The consumer's relevant state is the sibling's fetched mainline remote ref reported by `prepare-workspace.sh`. Grep that ref directly (Step 2).
- **Base is NOT mainline (a stacked PR / integration branch)** — the PR merges into a feature/integration branch, not develop. The code that **consumes** this new/changed contract very likely already lives **on that same integration effort**, not on develop. Grepping the sibling's develop here yields a **false "nothing consumes it"** or a **false "this breaks develop"** — develop is simply not the target. Adjust the search:
  1. **Same Linear key across repos** stays the strongest signal — a sibling PR/branch with the same `[A-Z]+-\d+` is the coordinated consumer. Find it with `gh pr list --repo <sibling> --search "<KEY>"` and read its diff.
  2. **Matching branch name.** The integration branch often has the same (or a parallel) name in the sibling. Detect it without checkout:
     ```bash
     git ls-remote --heads <sibling-remote> "*<KEY>*" "*<base-branch-slug>*"
     ```
     If it exists, the consumer adaptation probably lives there — read it via `gh api repos/<owner>/<repo>/contents/<path>?ref=<branch>` or the sibling's PR diff, not via the checked-out develop.
  3. **The base branch itself** may already contain the consumer (the producer is being stacked on top of code that already calls it). Inspect the base branch's state (`gh api .../contents/<path>?ref=<baseRefName>`) rather than assuming develop.
  4. If you **cannot** inspect the integration state (no matching PR/branch found, no coordinated key), do **not** emit a hard `blocker` off a develop-only grep — you'd likely be wrong. Downgrade to a **note asking the author to confirm** the consumer on the integration branch, and say explicitly that you reviewed against develop because the base branch state wasn't available.

The rule of thumb: **the consumer lives wherever this producer is being integrated.** For a develop-targeted PR that's develop; for a stacked PR it's the integration branch/key — search there first, and treat a develop-only grep as low-confidence.

## Step 1 — does the diff touch a contract surface?

Only run cross-repo analysis when the diff changes something another repo can observe. Contract surfaces:

**Backend / intelligence-api (producer):**
- **API routes** — added/renamed/removed paths in `urls.py`, router `register(...)`, or a changed URL prefix/`basename`. A moved or renamed route is a hard break for any caller.
- **Response shape** — a serializer field renamed, removed, retyped, or made conditional; a nested serializer restructured; pagination/envelope changes. Fields *added* are usually safe (see classification).
- **Request contract** — a new **required** field/query param, a renamed param, a stricter validator, a changed default that flips behavior.
- **Enums / choices / status values** — a renamed or removed `TextChoices`/constant whose string value crosses the wire.
- **Auth/permission scope** — a route that changed required permission/role (a consumer may now get 403).
- **Async/event contracts** — task names, queue/topic names, webhook payloads, cron-produced artifacts consumed elsewhere.

**Frontend (producer, rarer):** a shared type/DTO or a published package export that another frontend imports.

**Scrapers:** the swarm request/response contract (`scrapers_swarm_client.py` on the backend ↔ `scrapers-swarm` service).

If the diff touches none of these, skip cross-repo analysis and note nothing.

## Step 2 — find the consumers

For each contract surface the diff touches, extract the **stable token** a caller would use and grep the sibling repos for it. The token is the thing that crosses the wire, not the Python symbol name.

- **Route** → grep the **path string**, not the view class. Frontend calls are string URLs in the service layer.
  ```bash
  # Use the resolved root and each sibling's reported remote ref.
  git -C "$ROOT/reserhub-revenue-web" grep -n \
    "revenue-management/strategies" origin/main --
  # Partial paths too—callers often build URLs piecewise.
  git -C "$ROOT/reserhub-revenue-web" grep -nE \
    "strategies/[^\"']*upload" origin/main --
  ```
- **Response field** → grep the **serialized key** (JSON name, which may differ from the model attr if `source=`/`to_representation` rename it). Search consumer access patterns: `.raw_price`, `["raw_price"]`, `data.raw_price`, TS interfaces/Zod schemas.
  ```bash
  git -C "$ROOT/reserhub-revenue-web" grep -nE \
    "raw_price|rawPrice" origin/main --
  ```
- **Request field / query param** → grep where the consumer builds the request body or query string.
- **Enum / status value** → grep the **string literal value** (`"REVENUE_MANAGEMENT"`), not the Python member name.
- **Task/queue/webhook name** → grep the literal name string across producers and consumers.

Practical notes:
- The frontend consumer usually lives in a **service/api layer** (`services/`, `api/`, `*Service.ts`, `use*Query`/`use*Mutation` hooks) and in **TS types / Zod schemas**. Search both.
- Grep the value's **string form**, and check both `snake_case` and `camelCase` — some consumers remap keys at the boundary.
- Zero hits is a real signal: if a serialized field the PR renames has **no** consumer in any sibling, say so — it lowers the finding (or clears it).

## Step 3 — classify

Map the result into the existing gate; **do not** invent a new category. A confirmed break is `correctness` (critical → blocks). Use the ticket/PR body to check whether the break is intended and coordinated.

| What you found | Category / severity |
|---|---|
| Consumer in a sibling uses the removed/renamed route or field, and nothing in the diff (or a linked coordinated PR) updates it | `correctness`, **blocker/major** — blocks approval |
| Break exists **but** the PR body / linked Linear ticket says a paired consumer PR handles it (and you can see that PR or branch) | Note it as context in the comment; **don't block** on it alone — call out that the two must merge together. Prefer reviewing the paired PRs as a **group** (see batch grouping) |
| PR base is **not mainline** (stacked/integration branch) and you found the consumer adaptation on the matching key/branch (Step 0) | Not a break — the integration branch already consumes it. Note that the stack must merge in order |
| PR base is **not mainline** and you **cannot** inspect the integration state (no matching PR/branch, no key) | Do **not** hard-block off a develop-only grep. `correctness` **note** (not blocker) asking the author to confirm the consumer on the integration branch; state you reviewed against develop |
| New **required** request field/param with existing callers that don't send it | `correctness`, **major** |
| Additive-only change (new optional field, new route) with no consumer touched | Not a finding — additive is backward-compatible |
| Contract surface changed but grep finds **no consumer** in any sibling | Not a blocker; optionally a one-line note that the field/route appears unused cross-repo |
| Enum/status string value renamed and a consumer compares against the old literal | `correctness`, **major** |

## What to write

When you confirm a real cross-repo break, the inline comment goes on the **producer** line (the serializer/route in this PR's diff), in `tú` Spanish, and names the consumer concretely so the author can verify:

> Este endpoint renombra `raw_price` a `base_price`, pero `reserhub-revenue-web/src/services/strategyService.ts:88` todavía lee `raw_price` de la respuesta, así que la tabla de estrategias quedaría en blanco. Coordina el cambio con el front (o mantén el alias) antes de mergear.

Always cite the consumer as `repo/path:line` so it's a click away. If a coordinated consumer PR exists, name it and recommend merging them together rather than blocking outright.
