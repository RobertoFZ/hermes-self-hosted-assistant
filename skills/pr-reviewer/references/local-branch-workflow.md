# Local pre-PR branch workflow

Use this mode to review code before a GitHub PR exists. It is a read-only
preflight: inspect the current branch and working tree, optionally run requested
validations, and return a readiness verdict. Never post a GitHub review.

## Contents

- Absolute local rules
- Resolve scope and guidance
- Capture one review snapshot
- Recover intent without a PR body
- Inspect coordinated changes
- Review in two passes
- Apply the local readiness gate
- Output contract

## Absolute local rules

- Never commit, push, checkout, reset, rebase, stash, clean, create a PR, or
  modify the working tree/index.
- Do not fix findings unless the user separately asks for implementation.
- Fetching the base ref is allowed because it does not alter the working tree.
  Skip it when the user requests an offline review.
- Include committed, staged, unstaged, and untracked work in the snapshot.
- Match the user's language in chat. Spanish GitHub comment style is required
  only for text that will be posted to GitHub.

## 1. Resolve scope and guidance

Run the repository `bootstrap` skill first. Resolve the current repository with:

```bash
git rev-parse --show-toplevel
git remote get-url origin
git branch --show-current
git status --short
```

Load the same repository and test guidance required by step 4 of
`references/workflow.md`.

Use an explicit base named by the user first. Otherwise use the repository's
default branch:

| Repository | Base |
|---|---|
| `reserhub-revenue-full` | `main` |
| `price-engine-python` | `develop` |
| `reserhub-revenue-web` | `develop` |
| `reserhub-revenue-admin` | `develop` |
| `reserhub-intelligence-api` | `develop` |
| `scrapers-swarm` | `develop` |

If the repository is unknown, query
`gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`. Verify the
chosen ref exists before diffing. Never guess a missing base.

## 2. Capture one review snapshot

Unless offline, refresh only the selected base:

```bash
git fetch origin <base>
```

Resolve the merge base and inspect the aggregate tracked diff from that commit
through the current working tree:

```bash
git merge-base "origin/<base>" HEAD
git diff --find-renames --stat <merge-base> --
git diff --find-renames --name-status <merge-base> --
git diff --find-renames <merge-base> --
git ls-files --others --exclude-standard
```

`git diff <merge-base>` intentionally includes committed branch changes plus
staged and unstaged tracked changes. Read every untracked source/test/config
file separately and treat it as an added file.

Record:

- repository, current branch, base, merge-base SHA, and HEAD SHA;
- dirty/untracked state;
- changed files, additions/deletions, commits ahead/behind;
- whether the branch exceeds 20 files or roughly 500 changed lines.

If the current branch is the protected base, report the workflow violation. If
the tree is clean there is nothing to review; if it is dirty, review the local
changes but mark branch creation as required before PR readiness.

Do not rerun snapshot commands after starting the review without first checking
whether HEAD or `git status --short` changed. If they changed, tell the user the
snapshot moved and restart the analysis against the new state.

## 3. Recover intent without a PR body

Infer the Linear key from the branch name, commits, or matching OpenSpec change.
Read the Linear issue when available. Use its acceptance criteria to sharpen,
not expand, scope.

If no ticket or OpenSpec artifact is available, use the user's stated goal and
commit messages. Continue when intent is sufficiently clear; otherwise report
the missing context as a review limitation instead of inventing requirements.

## 4. Inspect coordinated changes

For a monorepo-root branch, inspect both root files and changed submodule
gitlinks:

```bash
git diff --submodule=log <merge-base> --
git diff --raw <merge-base> --
```

For every changed gitlink, resolve the base SHA from the root merge-base. Do not
trust the raw diff's new SHA when it is all zeroes: Git uses that value for a
dirty submodule working tree.

```bash
git rev-parse "<merge-base>:<submodule>"
git -C <submodule> rev-parse HEAD
git -C <submodule> status --short
git -C <submodule> diff --find-renames <base-gitlink-sha>
git -C <submodule> ls-files --others --exclude-standard
```

The submodule diff against `<base-gitlink-sha>` includes commits at its current
HEAD plus staged/unstaged tracked work. Read its untracked files separately.
If the submodule is not initialized or the base object is unavailable, report
that limitation instead of substituting an all-zero or guessed SHA.

Aggregate changed-file and changed-line counts from the root's non-gitlink
files and the actual submodule diffs. The root `--stat` reports a dirty gitlink
as only one short line and is not the true branch size.

Group submodule ranges with the same Linear key and review them as one behavior
change. Apply `references/cross-repo-impact.md` to contracts. If a coordinated
sibling branch/ref exists, inspect it with `git show`/`git diff` against its
base; never switch branches to do so. If it cannot be inspected, state the
uncertainty and do not claim a confirmed cross-repo break from a stale sibling
checkout alone.

## 5. Review in two passes

1. Apply `references/boundary-risk-checklist.md` and build the behavior map.
2. Review every changed file against `references/review-categories.md`,
   `references/severity-rubric.md`, and the applicable migration/cross-repo
   references.

Subtract CI-owned findings using `references/ci-already-covered.md`. Before a
PR, those tools may not have run: do not convert their surface into review
comments. If the user requests validation, load the repository testing skills,
run the scoped project commands, and report failures under `Validation` rather
than duplicating them as semantic review findings.

Inspect whether focused tests exist for every changed behavior. Missing or
ineffective coverage remains a `test_coverage` finding even when the current
suite passes.

## 6. Apply the local readiness gate

Use the same blocking definition as PR review:

- any `correctness`, `security`, `migration_safety`, or `test_coverage`
  finding blocks readiness at any severity;
- any `blocker` or `major` finding in any category blocks readiness.

Verdicts:

- `NOT_READY` — at least one blocking finding, protected-base violation, or a
  requested required validation failed.
- `READY_WITH_COMMENTS` — no blocking findings; only non-blocking findings
  remain.
- `READY_FOR_PR` — no findings block and requested validations passed.

If no validations were requested/run, `READY_FOR_PR` means the semantic review
gate passed, not that CI is green. State the unrun validations explicitly.

## 7. Output contract

Return:

1. verdict and one-sentence reason;
2. snapshot: repository, branch, base, merge-base/HEAD, dirty state, size;
3. blocking findings, highest severity first, with `path:line`, category,
   consequence, and concrete fix/test;
4. non-blocking findings;
5. validation run/pass/fail/not-run;
6. cross-repo or coordinated-branch dependencies;
7. concise next actions before PR creation.

Do not emit `APPROVE`/`COMMENT` events and do not use the GitHub dry-run JSON
contract for local mode.
