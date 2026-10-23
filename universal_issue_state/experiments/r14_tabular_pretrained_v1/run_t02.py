"""Additive T02 entry point; accepted T01 files are never modified."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from kden_r14_tabular.t02_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
