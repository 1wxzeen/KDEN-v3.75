"""Owner entry point for the audited T04 boolean-only serialization repair."""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from kden_r14_tabular.t04_serialization_repair import main
if __name__ == "__main__":
    raise SystemExit(main())
