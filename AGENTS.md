# Project rules

- This is an instance-neutral product repository. Never copy private home profiles,
  Recorder exports, device IDs, presence, endpoints, credentials, or workspace history.
- Version 0.1 is observation-only. No Home Assistant actuator service calls belong
  in its runtime. Control takeover is a later version gated by the migration ADR.
- Keep the domain engine free of Home Assistant imports, I/O and wall-clock reads.
  Pass time and immutable snapshots explicitly. Test failures and boundaries.
- Keep configuration versioned and validated; reject NaN, ambiguous price units,
  overlapping tariffs and duplicate actuator bindings.
- Use stable zone/plant IDs, native entities, translations, lifecycle cleanup and
  redacted diagnostics. Do not fabricate compressor activity or savings.
- Run `python -m unittest discover -s tests -v` and the isolated HA smoke test before
  release. CI is not a production deployer. No public push without publication scope.
