# Project rules

- This is an instance-neutral product repository. Never copy private home profiles,
  Recorder exports, device IDs, presence, endpoints, credentials, or workspace history.
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
