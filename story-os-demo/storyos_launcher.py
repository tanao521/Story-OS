from __future__ import annotations
import os
from pathlib import Path
def main() -> None:
    os.chdir(Path(__file__).resolve().parent)
    from main import main as command_main
    command_main()
