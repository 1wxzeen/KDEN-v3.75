from pathlib import Path
import hashlib,json
P=Path(__file__).resolve().parent
r={'schema':'R14_S5_IMPLEMENTATION_RELEASE_V1','files':{p.relative_to(P).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(P.rglob('*')) if p.is_file() and p.name!='RELEASE.json' and '__pycache__' not in p.parts}}
r['record_sha256']=hashlib.sha256((json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode()).hexdigest();(P/'RELEASE.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
