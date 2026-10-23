from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
files={p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file() and p.name!='RELEASE.json' and '__pycache__' not in p.parts}
r={'schema':'R14_S3_IMPLEMENTATION_RELEASE_V1','status':'S3_IMPLEMENTATION','files':files,'baseline_retrained':False,'full_nested_run_completed':False}
r['record_sha256']=hashlib.sha256((json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode()).hexdigest()
(root/'RELEASE.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
