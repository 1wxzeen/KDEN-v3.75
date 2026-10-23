"""Experiment-local entry point; no installation or legacy imports required."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from kden_r14_tabular.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
