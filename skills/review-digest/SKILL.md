---
name: review-digest
description: Build a concise Slack-ready digest from verified Hermes-initiated Codex PR reviews persisted during the previous 24 hours, including Linear product context and review insights. Use for the scheduled daily digest or an explicit digest preview.
---

# Review Digest

Use only persisted, GitHub-verified review data. Do not query open PRs, rerun a
review, or import reviews created outside the Hermes delegation flow.

## Required flow

1. Run:

   ```bash
   python3 /opt/review-automation/review_automation.py digest-source --hours 24 --timezone "${TZ:-America/Mexico_City}"
   ```

2. Read the returned JSON and produce the final Slack message. The scheduled
   Hermes cron delivers that final response; do not call a Slack send tool.
3. When `review_count` is zero, return a short message saying there were no
   verified PR reviews in the stated 24-hour window.
4. Otherwise group the digest by product impact, then list each PR with:
   repository and PR link, approval/comment result, related Linear issue and
   product summary when available, and the most important findings or risks.
5. End with compact cross-review insights: recurring risks, test gaps, or
   product areas affected. Do not invent trends from a single review.

Keep the message concise enough for a Slack DM. Explicitly mark missing or
unavailable Linear context instead of guessing it.
