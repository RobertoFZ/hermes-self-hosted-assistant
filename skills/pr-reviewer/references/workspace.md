# Review workspace

Use this procedure for GitHub single-PR, scoped-batch, and default-batch modes.
Do not use its fetch mode for local pre-PR reviews.

## Resolve and refresh

Run from the skill directory:

```bash
scripts/prepare-workspace.sh --fetch
```

The script resolves the monorepo in this order:

1. `REVIEW_MONOREPO_ROOT` (or legacy `RESERHUB_MONOREPO_ROOT`), when set;
2. the current Git checkout or one of its ancestors;
3. the standard Docker path `/opt/data/repos/reserhub-revenue-full`;
4. `$HOME/code/<owner>/<repository>` from `REVIEW_MONOREPO_REPOSITORY`.

It validates the configured monorepo origin and every submodule named by
`REVIEW_SUBMODULES`. `--fetch` updates only remote-tracking refs with
`git fetch --prune`; it never pulls, checks out, resets, or updates the working
tree or index. If network authentication fails, rerun with `--check`, continue
with the available refs, and disclose that cross-repo evidence may be stale.

The first output line is `MONOREPO_ROOT=<absolute-path>`. Treat that value as
the root for every repository read. Do not rely on the process working
directory.

## Choose the consumer state

For a mainline-targeted PR, search the sibling's fetched default remote ref,
preferring `origin/develop`, then `origin/main`, then `origin/master` when
`origin/HEAD` is unavailable. Example:

```bash
ROOT=/absolute/path/from-the-script
git -C "$ROOT/reserhub-revenue-web" grep -n "raw_price" origin/main --
```

For a stacked or integration-branch PR, follow
`references/cross-repo-impact.md`: inspect the coordinated PR, matching branch,
or integration base through `gh`/GitHub rather than treating mainline as the
consumer state.

Use checked-out files only when the required remote ref is unavailable. State
that fallback explicitly; zero local hits are not strong evidence when the
checkout or ref may be stale.
