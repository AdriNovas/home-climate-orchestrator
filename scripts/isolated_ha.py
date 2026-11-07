"""Linux namespace-container HA checks without network, home or inherited env.

Usage: python scripts/isolated_ha.py --python /path/to/ha-venv/bin/python
Docker CI remains the release matrix. Never pass a production Python/config.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

SUITES = [
    "ha_smoke",
    "ha_lifecycle",
    "ha_config_flow",
    "ha_execution",
    "ha_number",
    "ha_humidity_accounting",
    "ha_feedback_display",
    "ha_dry_session_policy",
    "ha_profiles_activity",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python", required=True, help="Disposable HA virtualenv Python"
    )
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--suite", action="append", choices=SUITES)
    args = parser.parse_args()
    if not shutil.which("bwrap"):
        parser.error("bubblewrap is required; use the isolated Docker CI instead")
    python = Path(args.python).absolute()
    prefix = subprocess.check_output(
        [str(python), "-I", "-c", "import sys; print(sys.prefix)"], text=True
    ).strip()
    if prefix in ("/", "/usr", "/usr/local"):
        parser.error(
            "A disposable virtualenv is required, not a system/production Python"
        )
    root = Path(__file__).resolve().parents[1]
    logs = args.logs or Path(tempfile.mkdtemp(prefix="hco-ha-results-"))
    logs.mkdir(parents=True, exist_ok=True)
    # Entirely new namespaces and environment. Only the runtime and neutral repo
    # are readable; config/storage are writable solely in ephemeral /tmp.
    command = [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/etc",
        "--ro-bind-try",
        "/etc/ld.so.cache",
        "/etc/ld.so.cache",
        "--ro-bind",
        prefix,
        prefix,
        "--ro-bind",
        str(root),
        "/repo",
        "--chdir",
        "/repo",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "PATH",
        str(python.parent) + ":/usr/bin",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "TZ",
        "UTC",
        str(python),
    ]

    def run(suite):
        with (logs / (suite + ".log")).open("w") as stream:
            try:
                result = subprocess.run(
                    command + ["tests/" + suite + ".py"],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=90,
                )
                return {"suite": suite, "exit_code": result.returncode}
            except subprocess.TimeoutExpired:
                return {"suite": suite, "exit_code": 124}

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(run, args.suite or SUITES):
            print(json.dumps(result), flush=True)
            results.append(result)
    (logs / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        json.dumps(
            {
                "logs": str(logs),
                "passed": sum(x["exit_code"] == 0 for x in results),
                "total": len(results),
            }
        )
    )
    return int(any(x["exit_code"] != 0 for x in results))


if __name__ == "__main__":
    raise SystemExit(main())
