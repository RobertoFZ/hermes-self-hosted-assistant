# gh runbook

All commands use `--repo <owner>/<repo>` so they work from anywhere.
`<owner>/<repo>` is the monorepo root or one of its five submodules:
`reservamos/reserhub-revenue-full`, `reservamos/price-engine-python`,
`reservamos/reserhub-intelligence-api`, `reservamos/reserhub-revenue-web`,
`reservamos/reserhub-revenue-admin`, or `reservamos/scrapers-swarm`.

## Contents

- Never merge
- Discover PRs
- Read current-head context
- Re-review prior comments
- Handle scratch data safely
- Handle explicitly requested self-reviews
- Submit approve/comment reviews
- Language policy

## NEVER merge

> **Do NOT run `gh pr merge`, `gh api ... -X PUT .../merge`, or any merge/close/squash/rebase-merge call. Ever. Under any circumstance.** You approve at most; a human merges. If asked to merge, decline and explain that this skill only reviews.

## Discover PRs (batch mode, read-only)

List open, ready (non-draft) PRs in a repo:

```bash
gh pr list --repo <owner>/<repo> --state open --draft=false \
  --json number,title,author,isDraft,headRefOid,reviewDecision,updatedAt --limit 50
```

Author scope — **by default exclude your own PRs**. A direct PR number/URL or an explicit request to include/review your own PRs overrides discovery filtering, but never the prohibition on self-approval. Filter client-side on the JSON above:
```bash
ME=$(gh api user --jq .login)
# keep only PRs NOT authored by you (default):
gh pr list --repo <owner>/<repo> --state open --draft=false \
  --json number,title,author,isDraft,headRefOid --jq "[.[] | select(.author.login != \"$ME\")]"
# only your own (when the user explicitly asks to review theirs):
gh pr list --repo <owner>/<repo> --state open --draft=false --author "@me" \
  --json number,title,author,isDraft,headRefOid
```

Idempotency — skip PRs you already reviewed at their current head commit:

```bash
ME=$(gh api user --jq .login)
# your last review on this PR (null if none):
gh api repos/<owner>/<repo>/pulls/<n>/reviews --paginate \
  --jq "[.[] | select(.user.login==\"$ME\")] | last | {state, commit_id}"
# current head commit of the PR:
gh pr view <n> --repo <owner>/<repo> --json headRefOid --jq .headRefOid
```

Review the PR if there is no prior review by you, or if your last review's `commit_id` differs from the current `headRefOid` (new commits landed). Otherwise skip it and say so.

## Read context (read-only)

```bash
gh pr view <n>  --repo <owner>/<repo> --json title,body,files,additions,deletions,author,commits,baseRefName,headRefName,headRefOid,statusCheckRollup
gh pr diff <n>  --repo <owner>/<repo>
# existing reviews/comments — so you don't duplicate humans or bots:
gh api repos/<owner>/<repo>/pulls/<n>/reviews  --paginate
gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate
```

REST reviews/comments do not expose the complete current thread state. Load
resolved/outdated state with GraphQL (the comment object does not expose
`diffSide`; `path`, `line`, and `originalLine` are sufficient):

```bash
gh api graphql -f query='
  query($owner:String!, $repo:String!, $n:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$n) {
        reviewThreads(first:100) {
          nodes { isResolved isOutdated path line
            comments(first:100) {
              nodes { author { login } body path line originalLine url }
            }
          }
        }
      }
    }
  }' -F owner=<owner> -F repo=<repo> -F n=<n>
```

Inspect CI/review-tool annotations on the current head separately:

```bash
HEAD=$(gh pr view <n> --repo <owner>/<repo> --json headRefOid --jq .headRefOid)
gh api repos/<owner>/<repo>/commits/$HEAD/check-runs \
  --jq '.check_runs[] | {id,name,status,conclusion,completed_at,details_url}'
gh api repos/<owner>/<repo>/check-runs/<check-run-id>/annotations --paginate
```

The same head can have a prior and a rerun of one check. Prefer the current
completed/latest run for each check before classifying blockers. Codacy or
another review tool can have zero current annotations while a review thread
still exists, or vice versa; treat both sources independently and apply the CI
subtract list before raising your own finding.

To map an inline comment to a `line`, use the new-side line number from the diff hunk. The reviews API expects `line` (and optionally `side`, default `RIGHT`) for the file's position in the diff.

## Re-review — verify your prior comments were resolved

Runs when the PR moved head since your last review (see idempotency above). Before you can approve, confirm the blocking asks from your previous review were actually addressed — don't approve just because a blind re-run surfaced nothing.

Your own prior inline comments (what you asked for, and where):
```bash
ME=$(gh api user --jq .login)
gh api repos/<owner>/<repo>/pulls/<n>/comments --paginate \
  --jq "[.[] | select(.user.login==\"$ME\") | {id, path, line, body, in_reply_to_id}]"
```

Resolved-thread state (REST doesn't expose it; use GraphQL). A thread with `isResolved: true` was marked resolved by the author:
```bash
gh api graphql -f query='
  query($owner:String!, $repo:String!, $n:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$n) {
        reviewThreads(first:100) {
          nodes { isResolved isOutdated path line
            comments(first:1) { nodes { author { login } body } } }
        }
      }
    }
  }' -F owner=<owner> -F repo=<repo> -F n=<n>
```

For each prior **blocking** comment, judge against the new head: **resolved** (flagged code/logic changed to address it, or `isResolved`) or **still open**. A still-open prior blocking finding **blocks approval** — count it even if the current-diff pass didn't resurface it (it may be `isOutdated`, i.e. moved out of the visible diff). To nudge an open thread instead of re-posting the same comment, reply on the existing thread:
```bash
gh api repos/<owner>/<repo>/pulls/<n>/comments/<comment_id>/replies \
  -f body='Sigue pendiente esto: <razón breve>.'
```

## Handle scratch data safely

Prefer the `gh api` field flags shown below or pass JSON through standard input;
do not create a payload file merely to submit a review. Never write review
payloads, downloaded archives, or extracted repository snapshots under `/tmp`:
the Hermes container restricts file-tool writes to `/opt/data`.

If an intermediate artifact is unavoidable, write it beneath
`/opt/data/pr-reviewer-tmp/<repo>-<pr>-<head>/`, never inside a review checkout
or worktree, and remove it after use. Do not unset or broaden
`HERMES_WRITE_SAFE_ROOT` to accommodate scratch data.

## Explicitly requested self-reviews

Before choosing the review event, compare the authenticated account with the PR author:

```bash
ME=$(gh api user --jq .login)
AUTHOR=$(gh pr view <n> --repo <owner>/<repo> --json author --jq .author.login)
```

When `AUTHOR == ME`, continue only because the user directly named the PR or explicitly asked to include/review their own PRs. Analyze it with the same categories, severity rubric, and findings gate, but **never send `event=APPROVE`** because GitHub does not allow an author to approve their own PR. Submit `event=COMMENT` instead:

- With findings, keep the normal inline-comment and blocking-summary rules below.
- With no findings or inline comments, send a visible result with `-f event=COMMENT -f body='Autorrevisión solicitada: no encontré hallazgos, pero GitHub no permite aprobar un PR propio.'`.

Do not manufacture a finding to justify `COMMENT`; self-authorship is a submission constraint, not a code defect.

## Submit the review

You only ever submit one of two events: **APPROVE** or **COMMENT**. Never `REQUEST_CHANGES`.

### Gate passes and the PR is not self-authored → APPROVE

**No top-level body** — the approval event itself communicates it; don't add a note saying the PR is approved. Attach inline comments only for any `minor`/`nit` you still want to leave.

```bash
gh api repos/<owner>/<repo>/pulls/<n>/reviews \
  -f event=APPROVE \
  -f 'comments[][path]=dynamic_pricing/apps/web/views/v1/foo.py' \
  -f 'comments[][line]=42' \
  -f 'comments[][body]=Podrías mover este queryset a una variable antes de iterarlo, por estilo del repo, sin cambiar comportamiento.'
```

If there are zero comments, just send the event:

```bash
gh api repos/<owner>/<repo>/pulls/<n>/reviews -f event=APPROVE
```

### Gate fails → COMMENT (never REQUEST_CHANGES)

One inline comment per finding. The top-level `body` depends on how many **blocking** findings there are (blocking = critical category at any severity, or `blocker`/`major` anywhere):

- **More than one blocking finding →** set `body` to a terse list of *only* the blocking reasons (no acknowledgments/filler). See `comment-style.md`.
- **Exactly one blocking finding →** omit the top-level body; the lone inline comment carries the why.

**Multiple blocking findings — top-level body present:**
```bash
gh api repos/<owner>/<repo>/pulls/<n>/reviews \
  -f event=COMMENT \
  -f body='Bloquean la aprobación dos temas: el índice sobre TripObservation corre en transacción y bloquearía escrituras, y el endpoint nuevo perdió el filtro por provider. Lo detallo en línea.' \
  -f 'comments[][path]=dynamic_pricing/apps/web/migrations/0262_tripobservation_idx.py' \
  -f 'comments[][line]=12' \
  -f 'comments[][body]=Esta migración agrega un índice sobre TripObservation dentro de transacción... usa atomic = False con AddIndexConcurrently como en 0211_busline_seat_type_index.py.' \
  -f 'comments[][path]=dynamic_pricing/apps/web/views/v1/bar.py' \
  -f 'comments[][line]=88' \
  -f 'comments[][body]=Este endpoint nuevo perdió el filtro por provider en get_queryset... agrega provider=self.request.user.provider y deleted_at__isnull=True.'
```

**Single blocking finding — no top-level body:**
```bash
gh api repos/<owner>/<repo>/pulls/<n>/reviews \
  -f event=COMMENT \
  -f 'comments[][path]=dynamic_pricing/apps/web/migrations/0262_tripobservation_idx.py' \
  -f 'comments[][line]=12' \
  -f 'comments[][body]=Esta migración agrega un índice sobre TripObservation dentro de transacción... usa atomic = False con AddIndexConcurrently como en 0211_busline_seat_type_index.py.'
```

If your `gh`/GitHub rejects a `COMMENT` review with no `body`, post the lone inline comment via the comments endpoint instead (no review wrapper, no top-level body):
```bash
HEAD=$(gh pr view <n> --repo <owner>/<repo> --json headRefOid --jq .headRefOid)
gh api repos/<owner>/<repo>/pulls/<n>/comments \
  -f commit_id="$HEAD" -f path='...py' -F line=12 -f side=RIGHT \
  -f body='Esta migración agrega un índice sobre TripObservation...'
```

Notes:
- Repeat the three `comments[][path]` / `comments[][line]` / `comments[][body]` lines per finding; gh groups them positionally.
- Bodies must be informal `tú` Spanish (`comment-style.md`). No `nit:`/`bloqueante:` prefixes, no emoji.
- For multi-line comments use `-f 'comments[][start_line]=10' -f 'comments[][line]=14'`.
- If a comment targets a file/line not in the diff, attach it to the nearest changed line in that file or fold it into the top-level body rather than failing the call.

## Language policy for replies (if you also respond to threads)

- Replies to AI bots (`coderabbitai`, `chatgpt-codex-connector`): English.
- Replies to humans: Spanish.
- Your own review comments: always Spanish (per this skill).
