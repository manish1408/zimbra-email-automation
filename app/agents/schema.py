from __future__ import annotations

from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parent.parent / "graphs" / "spec" / "email_agent.yml"


def load_graph_schema() -> dict:
    with SPEC_PATH.open(encoding="utf-8") as handle:
        raw = handle.read()
    # Skip comment lines at top of spec file
    lines = [line for line in raw.splitlines() if not line.startswith("#")]
    return yaml.safe_load("\n".join(lines))
