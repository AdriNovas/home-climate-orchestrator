# Configurable, reliable autonomous operation

This is a readiness contract, not a certification that a particular home has
completed control handover. The planner, opt-in executor and existing external
controller are different authorities until an installation is commissioned.

## Configuration contract

Expose differences that belong to the house, plant, zone, tariff, meter or
source. A new option needs a versioned schema, bounded validation, a real runtime
consumer, effective-value diagnostics, translations, docs and lifecycle tests.
Show inheritance and precedence; accepted-session endpoints/deadlines remain
frozen where required. Editing options or upgrading must never enable control,
clear Manual, renew an attempt budget or change stable identities implicitly.

The policy currently exposes 43 numeric fields and six booleans in addition to
price bands. Numeric form ranges and model ranges share
`domain.models.POLICY_NUMERIC_BOUNDS`; cross-field constraints still apply.
Zero must be labelled by meaning: an unlimited session is not a disabled safety
check. See [configuration](CONFIGURATION.md).

Candidate 0.2.0a9 groups all 49 scalar policy controls in six native forms,
retains the complete advanced form, offers typed per-source clock editing and
shows field-specific relational errors. Isolated native flows verify persistence,
runtime consumption, clearing and preservation of other groups/contracts,
Manual and identities. This is not authenticated frontend or installation proof.
Next usability work: report why each effective value was inherited or blocked.

## Non-negotiable execution invariants

- Explicit permission and a verified single writer; an exclusivity declaration
  cannot detect every external automation in the ecosystem.
- Fresh sources, compatible plant direction, hardware limits and Manual/ownership
  precedence. More configuration must not offer a way to bypass these.
- Persist intent and budgets before emission; re-read authority after waits and
  persistence. Service return is not actuator ACK. Ambiguous starts are not
  blindly replayed after timeout or restart.
- Corrupt nested journals fail closed, preserve original bytes and release
  claims; do not automatically delete evidence to resume control.
- Safety ticks, urgent events and absolute deadlines remain independent of
  routine plan coalescing. See [cadence](PLANNING_CADENCE.md).
- Shared-plant incident/lockout policy requires a coherent plant-scoped model;
  room counters and configurable concurrency are not proof of that capability.

## Acceptance before a home handover

Use the actual HA managers for setup, options, reload, failure and removal, in
addition to deterministic engine tests. Test cold start, partial persistence,
late echoes, unavailable actuators, stale sources, permission loss, Manual races,
tariff boundaries, plant conflicts, critical cuts, downgrade and rollback.
Preserve identity, measured energy, ownership, absolute deadlines and budgets.

Prove an isolated full restore of a representative backup and reconcile the
complete installation profile with every external emitter before enabling the
new writer. Then inspect the authenticated UI and observe natural comparable
episodes. Operating mode is not evidence of compressor work, moisture removal
or savings. See [migration gates](MIGRATION.md).

Scope-specific authority leases, shared demand latches and their authenticated
opposition/recovery protocol require implementation and adversarial acceptance
before they may replace an installation's existing authority contract. They are
not provided merely by exposing more scalar options.
