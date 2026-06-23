from __future__ import annotations

import subprocess
import sys
from pathlib import Path


APP_HOME = Path(__file__).resolve().parents[1]


def run_step(name: str, script: str, required: bool = True) -> int:
    print(f"== {name} ==")
    result = subprocess.run(
        [sys.executable, str(APP_HOME / "scripts" / script)],
        cwd=APP_HOME,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        message = f"{name} failed with exit code {result.returncode}"
        if required:
            raise SystemExit(message)
        print(message, file=sys.stderr)
    return result.returncode


def main() -> None:
    run_step("card/nowcast indicators", "collect_card_indicators.py", required=True)
    run_step("kosis indicators", "collect_kosis_indicators.py", required=False)


if __name__ == "__main__":
    main()
