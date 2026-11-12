# Optional drying reservation guards

Existing profiles retain their behavior: `dry_max_temperature_drop=null`,
`dry_dewpoint_completion=false`, and `humidity_debt_urgency=true`.
These split-only options do not enable physical execution or take Manual authority.

- `dry_max_temperature_drop`: optional 0–10°C differential below the temperature
  captured when the reservation is accepted. Equality continues; a larger fall
  stops. Missing required acceptance metadata fails closed rather than inferring
  it from a later reading. The live common thermal floor and other guards remain.
- `dry_dewpoint_completion`: require humidity at/below the accepted stop target
  **and** dew point at/below the frozen target throughout `humidity_recovery_s`.
  The frozen target is `round(dew_point(accepted_floor, accepted_humidity_stop), 3)`,
  not the measured starting dew point. A later tariff/target edit does not renew
  the reservation or replace this reference. Invalid metadata stops the session.
- `humidity_debt_urgency=false`: accumulated debt no longer grants urgency;
  the debt counter is retained and independent high/severe humidity predicates
  remain active. This does not implement a household-wide humidity latch.

The executor journal persists accepted reservation metadata before the observer
store. Restore reconciles an owned dry reservation from that journal, including
an interruption between the two saves. Observer `dry_memory_schema: 1` stores
new fields in a sidecar; legacy zone rows exclude those fields so preceding
versions do not discard their entire memory row for unknown constructor keys.
Unknown schemas/fields and invalid numeric metadata are rejected. Binding
mismatch must never transfer ownership to another physical entity.

Coverage includes core guard boundaries, timer interruption/roundtrip, real
coordinator persistence/watchdog methods with Store doubles, and an independent
static review. A private captured-YAML replay checks nine valid-metadata exit
cases using the real HA Template evaluator. These checks are not a complete
restart/upgrade/downgrade, multi-zone control replay or physical proof. A shared
humidity latch, authority opposition and complete adapter parity remain separate
work. No integration release or installed control transfer is certified here.
