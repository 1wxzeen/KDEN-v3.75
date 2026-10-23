"""Maintainer-only implementation seal; never used during model execution."""
from pathlib import Path
import hashlib, json
ROOT = Path(__file__).resolve().parent
def digest(value): return hashlib.sha256((json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)+'\n').encode()).hexdigest()
record = {'schema': 'R14_S4_IMPLEMENTATION_RELEASE_V1', 'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and p.name != 'RELEASE.json' and '__pycache__' not in p.parts}, 'full_historical_run_performed': False}
record['record_sha256'] = digest(record)
(ROOT/'RELEASE.json').write_text(json.dumps(record, indent=2, sort_keys=True)+'\n')
