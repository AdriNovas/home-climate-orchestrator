# Common drying floor (opt-in)

Set policy `dry_heat_offset` to a finite °C differential (e.g. -0.5) in a profile to use max(configured day/sleep floor or valid bound floor, current ambient heat goal + offset) for both admission and continuation. The extra `dry_margin` is ignored only in this mode. Missing bound floor blocks a start and stops an owned session. No wall clock, lease, cooldown or attempt counter is reset by a goal change. Default null preserves all previous behavior. Existing physical authority is never enabled by upgrading.

This feature is a thermal predicate, not full parity with any external controller. It does not remove native session caps, budgets, ownership or plant arbitration. A controller providing continuous, multi-head, humidity-cohort drying must remain the sole writer until its complete migration contract is verified. Household policy and domestic target tables are private and are not shipped as product defaults.
