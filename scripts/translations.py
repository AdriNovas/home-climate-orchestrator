"""Validate canonical English/Spanish UI catalogues and sync HA strings.json."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/climate_orchestrator"


def keys(value, prefix=""):
    if not isinstance(value, dict):
        return {prefix}
    return {
        key for name, child in value.items() for key in keys(child, prefix + "/" + name)
    }


english = json.loads((ROOT / "translations/en.json").read_text())
spanish = json.loads((ROOT / "translations/es.json").read_text())
assert keys(english) == keys(spanish), "English and Spanish UI fields differ"
(ROOT / "strings.json").write_text(
    json.dumps(english, ensure_ascii=False, indent=2) + "\n"
)
print("English/Spanish fields match; strings.json synchronized")
