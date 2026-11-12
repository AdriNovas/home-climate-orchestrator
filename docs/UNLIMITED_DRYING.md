# Unlimited drying: candidate behavior

Opt-in execution behavior in the 0.2 alpha. Existing defaults remain bounded. An explicit maximum of zero means no service-duration cap, for a split or an independent dryer; nonzero limits still stop sessions. Minimum service, fault/ACK, source age and other safety clocks remain independent. Scheduling an unlimited session uses the minimum service interval to seek a tariff opportunity, not a zero-length interval or an infinite reservation.

Memory stores `dry_active` independently from `dry_until`. Legacy positive deadlines are still recognized. New accepted sessions set active; Manual or confirmed off clears it. A zero expiry alone is not an end-of-session marker. Restored actuator bindings must still match. Watchdog exits remain active with zero expiry.

Validation: domain tests cover eight hours of owned drying and missing temperature/humidity, thermal floor, permission, pause and persistence. The isolated HA humidity/accounting suite exercises the actual watchdog with an unlimited owner and its native adapter with fictional devices; lifecycle checks setup/reload/unload/removal. These do not certify a multi-zone production handover or energy savings.

## Optional admissions and service budgets

Duration, admissions and service budgets are separate settings. Existing profiles
retain `dry_concurrent: false` and `dry_budget_enabled: true` on upgrade. A zero
maximum does not implicitly enable concurrency or disable a budget.

With `dry_concurrent: true`, more than one head can be admitted on a shared plant
when each head has valid drying demand and its humidity is within
`dry_humidity_band` percentage points (default 5) of the highest eligible demand
or healthy owned drying session on that plant. The boundary is inclusive. A
Manual, stale or vetoed head cannot reserve the band. Existing owned sessions
retain their own endpoint and protective exits; a later higher demand does not
stop them merely because they fall outside the new admission band. Native
transactions remain serialized per plant; permitted drying operation can overlap.
This admission option does not clear a room's thermal-failure latch. Repeated
protective stops must survive handover and require a separately reviewed,
auditable requalification before another drying attempt. The allowed humidity
band alone is not evidence that a previously stopped head is safe to retry.

With `dry_budget_enabled: false`, normal admission ignores the per-day attempt
quota and service cooldown, including the independent dryer's service cooldown.
Existing attempt, last-attempt and debt history is retained, including across a
local date boundary while evaluated with the budget disabled. Re-enabling within
the same recorded local day does not grant a fresh allowance. If restored memory
still records an earlier day and the budget is enabled before the next
evaluation, the legacy new-day quota reset still applies. This setting does not
promise immutable lifetime attempt totals across all restart/toggle orders.
This switch does **not** disable maximum duration, observed plant minimum-off,
reversal/compatibility, floors, sources, permission, pause/Manual, an independent
dryer's episode-recovery latch, or the executor's ambiguous-command Manual latch.
It does not certify a household's fault-recovery policy or implement a complete
writer handover. Tests use fictional devices; no production activation occurs.
