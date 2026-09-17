---
name: review-digest
description: Build a concise Slack-ready digest from verified Hermes-initiated Codex PR reviews and private proposals that exhausted their two reminders. Use for the scheduled daily digest or an explicit digest preview.
---

# Review Digest

Use only persisted workflow data. Keep GitHub-verified reviews separate from
active private proposals that have exhausted their two reminders. Do not query
open PRs, rerun a review, or import reviews created outside the Hermes
delegation flow.

## Required flow

1. Reconcile terminal review-session cleanup before building the digest:

   ```bash
   python3 /opt/review-automation/review_automation.py cleanup --limit 100
   ```

   Continue to the digest even when an individual cleanup retry fails; cleanup
   state remains persisted for the next retry.
2. Run:

   ```bash
   python3 /opt/review-automation/review_automation.py digest-source --hours 24 --timezone "${TZ:-America/Mexico_City}"
   ```

3. Read the returned JSON and produce the final Slack message. The scheduled
   Hermes cron delivers that final response; do not call a Slack send tool.
4. When `review_count` and `pending_review_count` are both zero, return a short
   message saying there were no verified PR reviews or pending decisions.
5. When verified reviews exist, group them by product impact, then list each PR with:
   repository and PR link, approval/comment result, related Linear issue and
   product summary when available, and the most important findings or risks.
6. When `pending_reviews` is non-empty, add a separate **Pending decisions**
   section. List each repository/PR link, revision token, objective, and compact
   summary. Never count or describe these as published or verified reviews.
7. End with compact cross-review insights: recurring risks, test gaps, or
   product areas affected. Do not invent trends from a single review.

Keep the message concise enough for a Slack DM. Explicitly mark missing or
unavailable Linear context instead of guessing it.
