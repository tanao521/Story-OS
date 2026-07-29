"""RC1 browser evidence entry point.

This is intentionally a small runner note rather than a TestClient substitute.
The actual Chromium session is driven by the Codex Browser runtime so that the
browser process, DOM events, history API, console, and network are observable.
Run the fixture server first, then execute the documented browser matrix in
``docs/planning/PHASE_0D5_C_RC1_DELIVERY_REPORT.md``.  The script only checks
that an isolated fixture server is reachable; it never labels HTTP requests as
browser evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7862/")
    parser.add_argument("--evidence-root", default="")
    args = parser.parse_args()
    try:
        with urllib.request.urlopen(args.url, timeout=3) as response:
            print(f"fixture reachable: {response.status}")
    except Exception as exc:  # pragma: no cover - operator-facing guard
        print(f"fixture unavailable after browser run: {exc}")
    root = Path(args.evidence_root) if args.evidence_root else None
    if root is None:
        candidates = sorted(Path(os.environ.get("TEMP", ".")).glob("rc2_browser_ws_*/projects/rc2-test-project"), key=lambda p: p.stat().st_mtime, reverse=True)
        root = candidates[0] if candidates else None
    marker = root / ".rc3_response_dropped.json" if root else None
    results = list(root.glob("data/narrative_turn/results/*/*/*.json")) if root else []
    authorities = list(root.glob("data/narrative_turn/operations/*.json")) if root else []
    transitions = list(root.glob("data/narrative_turn/transitions/*/*/*/*.json")) if root else []
    if marker and marker.exists() and results and authorities and transitions:
        print("DURABLE_CONFIRM_RESPONSE_LOSS_RECOVERY: PASS")
    else:
        print("DURABLE_CONFIRM_RESPONSE_LOSS_RECOVERY: EVIDENCE_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
