---
name: review-reminder
description: Deliver due persisted PR-review reminders to their exact private Slack threads without producing a cron fallback message.
---

# Private PR Review Reminder

This skill is only a delivery worker. It must not choose a destination, post in
the source channel, analyze code, or make a GitHub change. It may open the
persisted decision owner's DM only when a recovered `proposal_deliveries` item
explicitly requires an `owner_dm` target.

## Required flow

1. Run the persisted 15-minute sweep:

   ```bash
   python3 /opt/review-automation/review_automation.py reminder-sweep --timezone "${TZ:-America/Mexico_City}"
   ```

   The sweep also reclaims expired analysis leases and checks each due PR's
   current lifecycle and head before returning delivery work.
2. For every item in `proposal_deliveries`, use the Slack send tool exactly
   once with the returned text and `delivery_key` metadata:

   - when `target_kind` is `owner_dm`, open a DM to the returned `channel_id`
     user ID and send the message as the DM root;
   - when `target_kind` is `channel`, send to the returned `channel_id` and
     `thread_ts`;
   - never substitute the cron target or source channel.

   After Slack returns a definite channel ID and message timestamp, acknowledge
   the same item:

   ```bash
   python3 /opt/review-automation/review_automation.py proposal-delivery-ack \
     --delivery-id "<delivery_id>" \
     --claimant "<claimant>" \
     --channel-id "<Slack channel ID>" \
     --message-ts "<Slack message timestamp>"
   ```

   If Slack definitively rejects the send, use `proposal-delivery-block`. If
   the outcome is ambiguous, do not retry or block it as definitely failed;
   leave the receipt for operator reconciliation.
3. For every item in `deliveries`, use the Slack send tool exactly once with:

   - channel: the returned `channel_id`
   - thread: the returned `thread_ts`
   - text: the returned `text`, unchanged

   Never use the cron delivery target as a fallback.
4. After Slack returns a definite message timestamp, acknowledge that same
   item:

   ```bash
   python3 /opt/review-automation/review_automation.py reminder-ack \
     --reminder-id "<reminder_id>" \
     --delivery-id "<delivery_id>" \
     --claimant "<claimant>" \
     --message-ts "<Slack message timestamp>" \
     --timezone "${TZ:-America/Mexico_City}"
   ```

5. If Slack definitively rejects a send, persist the failure with
   `reminder-block` using the returned IDs and claimant. If the Slack outcome
   is ambiguous, do not retry or block it as definitely failed; leave the
   receipt unacknowledged so the next sweep detects the ambiguity and blocks
   duplicate delivery for operator reconciliation.
6. After all returned items have been handled, return exactly:

   ```text
   NO_REPLY
   ```

Return `NO_REPLY` even when no reminders are due. Do not add any other text,
because the cron delivery target must never receive a top-level reminder run
message.
