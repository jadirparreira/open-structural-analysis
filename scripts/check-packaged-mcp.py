"""Validate an installed executable/AppImage over real MCP HTTP, without a source checkout."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="opensa-installed-check-") as temp:
        report = Path(temp) / "mcp-report.json"
        environment = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        environment["XDG_DATA_HOME"] = str(Path(temp) / "data")
        # extract-and-run exercises AppRun and the frozen binary, without requiring FUSE.
        command = [str(executable)]
        if executable.suffix == ".AppImage":
            command.append("--appimage-extract-and-run")
        command += ["--mcp-self-test", str(report)]
        result = subprocess.run(
            command,
            cwd=temp,
            env=environment,
            timeout=90,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if not report.is_file():
            raise SystemExit(
                f"No MCP diagnostic report (exit {result.returncode}): {result.stderr.decode(errors='replace')}"
            )
        data = json.loads(report.read_text(encoding="utf-8"))
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if result.returncode != 0 or not data.get("ok") or not data.get("frozen"):
            raise SystemExit("Installed MCP validation failed; do not publish this release.")


if __name__ == "__main__":
    main()
