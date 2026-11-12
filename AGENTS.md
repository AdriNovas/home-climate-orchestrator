# Project rules

- This is an instance-neutral product repository. Never copy private home profiles,
  Recorder exports, device IDs, presence, endpoints, credentials, or workspace history.
- Implement requested behavior in the integration with validated native options
  and runtime consumers. Do not substitute installation-specific YAML patches
  for missing product capabilities; iterate the candidate instead.
- Released version 0.1 remains observation-only. Develop opt-in execution in the
  0.2 candidate, separated from the pure planner and gated by the migration ADR.
  Never enable control as a side effect of upgrading an observation entry.
- Keep the domain engine free of Home Assistant imports, I/O and wall-clock reads.
  Pass time and immutable snapshots explicitly. Test failures and boundaries.
- Keep configuration versioned and validated; reject NaN, ambiguous price units,
  overlapping tariffs and duplicate actuator bindings.
- Use stable zone/plant IDs, native entities, translations, lifecycle cleanup and
  redacted diagnostics. Do not fabricate compressor activity or savings.
- Run `python -m unittest discover -s tests -v` and the isolated HA smoke test before
  release, plus `python tests/ha_lifecycle.py` for native setup/reload/removal.
  CI is not a production deployer. No public push without publication scope.
- For config/options UI changes, run `python tests/ha_config_flow.py` in isolated
  Home Assistant. Use the real flow managers, not only direct step calls: schema
  defaults can silently restore optional bindings the user cleared. Verify
  setup/edit/reload/removal, stable IDs and preservation of vendor devices.
- For native target entities, run `python tests/ha_number.py`: exercise actual
  number services and rapid edits. Table-only changes must not unload entities
  between commands or lose a cell; revalidate and fence stale plans while
  preserving Manual, sessions, sources and execution authority.
- Keep negative-power noise handling opt-in and meter-scoped. Never silently
  relax supply protection, clamp energy counters, or accept real negative/net
  export as consumption. Test unit conversion, bounds and plant feedback.
- Run `python tests/ha_humidity_accounting.py` for humidity, standalone dryers
  and period accounting. Use a disposable HA container without production
  mounts, network, devices or inherited Supervisor credentials. Never bootstrap
  test HA inside the production container, even with a temporary config path.
- Preserve existing target IDs and authority on upgrade. Humidity sessions freeze
  their endpoint; a price change must not renew a lease or reset attempt budgets.
  Independent dryers need an independent plant and must reject water-adding
  humidifiers. Keep Manual, pauses, floors, maximum deadlines and vendor guards.
- Treat period totals as covered measurements, never reconstructed past or a
  full electricity bill. Test tariff boundaries, signed charges, DST, missing
  power/price, restart gaps, own-store recovery and overlapping meter scopes.
