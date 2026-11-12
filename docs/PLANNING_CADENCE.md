# Planning and safety cadence

The coordinator distinguishes full planning from live safety checks.

- A routine full plan runs no more often than every **300 seconds**. Ordinary
  source changes are coalesced until that review; the configured
  `command_interval` separately limits ordinary actuator calls.
- An authority, permission, Manual/actuator transition, missing or unavailable
  source, explicit user action, or other urgent event may request a full review
  immediately. The executor still re-reads permissions and ownership before an
  emission; an old queued decision is never authority.
- In control mode, guard-only checks still run on relevant state events and on a
  **60-second** safety tick. They validate supply and owned-drying exits
  (including freshness, permission, and thermal-floor guards) without
  recalculating the full price/comfort plan.
- If a decision's absolute `next_at` deadline is sooner than the regular
  300-second tick, a one-shot wake is scheduled for that deadline. Minimum-off,
  reversal, ACK, accepted-session, tariff-window and recovery clocks are not
  rounded to a polling interval or renewed by reload.
- Startup and explicit configuration or user commands may refresh immediately.
  The periodic interval is a maximum delay for ordinary planning, not a blanket
  delay for safety or a guarantee that every device responds physically within
  five minutes.

Tests cover the coalescing boundary, urgent bypass, earliest in-window deadline,
and the HA control-mode safety timer. Any change to this contract must preserve
event ordering, generation checks, serialized plant sends, and restart recovery.

An existing external controller remains a separate writer until that
installation's documented handover gate is closed. Candidate timing does not
change any external controller's poll or grant control authority.
