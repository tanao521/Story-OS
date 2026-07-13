from __future__ import annotations
import os, runpy, sys
from pathlib import Path
PROJECT_DIR = Path(__file__).resolve().parent / "story-os-demo"
def main() -> None:
    os.chdir(PROJECT_DIR)
    sys.path.insert(0, str(PROJECT_DIR))
    runpy.run_path(str(PROJECT_DIR / "main.py"), run_name="__main__")
if __name__ == "__main__":
    main()
