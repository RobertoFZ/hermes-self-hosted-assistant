# Collected PR 93 evidence

GitHub metadata reports 95 additions, 27 deletions, and 6 changed files. Discussion history is complete.

The private patch provides this evidence:

- Adds model class `CancellationReason`, backed by new table `cancellation_reasons` with `id`, unique non-null `code`, translated `name`, and timestamps.
- Modifies model class `Booking` with an optional `belongs_to :cancellation_reason` association during rollout.
- Adds nullable `bookings.cancellation_reason_id`.
- Adds index `index_bookings_on_cancellation_reason_id`.
- Adds foreign key `bookings.cancellation_reason_id -> cancellation_reasons.id` with the database's default restrictive delete behavior.
- Backfills existing cancelled bookings from their legacy reason text.
- A later migration validates the backfill and changes `bookings.cancellation_reason_id` from nullable to non-null.
- No tables or columns are deleted in this PR.
- The selected PR is not part of a stack and has no proven related OpenSpec.
