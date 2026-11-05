"""Read-only interoperability with bounded external transition ledgers.

These records describe expected echoes; they never grant automatic authority.
No helper is written, no lease renewed, and explicit user context always wins.
"""

import json
from math import isfinite

MODES = ("off", "heat", "cool", "dry", "fan_only", "auto")


def number(value):
    return type(value) in (int, float) and isfinite(value)


def record(raw):
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def transition_echo(raw, mode, target, old_mode, old_target, now, user=False):
    """Compact v1: [from_mode, from_target, to_mode, to_target, until, ack]."""
    if (
        user
        or mode not in MODES
        or old_mode not in MODES
        or any(v is not None and not number(v) for v in (target, old_target))
    ):
        return False
    data = record(raw)
    rows = data.get("q") if data else None
    if not isinstance(rows, list) or len(rows) > 3:
        return False
    for row in rows:
        if not isinstance(row, list) or len(row) != 6:
            continue
        before_mode, before_target, after_mode, after_target, until, ack = row
        if (
            type(before_mode) is not int
            or type(after_mode) is not int
            or before_mode not in range(len(MODES))
            or after_mode not in range(len(MODES))
            or any(
                v is not None and not number(v) for v in (before_target, after_target)
            )
            or not number(until)
            or not 0 <= until - now <= 60
            or type(ack) is not int
            or ack not in (0, 1)
        ):
            continue
        fm, tm = MODES.index(old_mode), MODES.index(mode)
        before = fm in (before_mode, after_mode) and old_target in (
            before_target,
            after_target,
        )
        toward = (
            tm in (before_mode, after_mode)
            and target in (before_target, after_target)
            and (tm == after_mode or target == after_target)
        )
        final = tm == after_mode and (after_target is None or target == after_target)
        if (ack == 0 and before and toward) or (ack == 1 and final):
            return True
    return False


def cut_record(raw):
    """An empty object is an initialized inactive fence; malformed is unknown."""
    data = record(raw)
    if data is None:
        return None
    active, at, released = (
        data.get("active", False),
        data.get("at", 0),
        data.get("released", 0),
    )
    if type(active) is not bool or not all(
        number(x) and x >= 0 for x in (at, released)
    ):
        return None
    return {"active": active, "at": at, "released": released}


def critical_echo(raw, cut_raw, mode, target, now, user=False):
    data, cut = record(raw), cut_record(cut_raw)
    if (
        user
        or not data
        or cut is None
        or mode not in MODES
        or target is not None
        and not number(target)
    ):
        return False
    if not number(data.get("at")) or data["at"] != cut["at"]:
        return False
    if mode == "off" and number(data.get("until")) and 0 <= data["until"] - now <= 120:
        return True
    old = data.get("old", [])
    return (
        cut["active"]
        and isinstance(old, list)
        and len(old) <= 6
        and number(data.get("late"))
        and 0 <= data["late"] - now <= 120
        and [MODES.index(mode), target] in old
    )


def journal_echo(data, binding, mode, target, now, user=False):
    """Public journal v1 consumer contract, independent of Home Assistant."""
    if (
        user
        or not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or target is not None
        and not number(target)
    ):
        return False
    if data.get("actuator") != binding or data.get("execution_mode") != "control":
        return False
    if data.get("temperature_unit") != "°C":
        return False
    if data.get("phase") not in ("sending", "acked", "uncertain"):
        return False
    expected = data.get("expected")
    if not isinstance(expected, list) or len(expected) > 4:
        return False
    for row in expected:
        if not isinstance(row, dict):
            continue
        until = row.get("until")
        wanted = row.get("target")
        if (
            number(until)
            and 0 <= until - now <= 60
            and mode == row.get("mode")
            and (wanted is None or number(wanted) and target == wanted)
        ):
            return True
    return False
