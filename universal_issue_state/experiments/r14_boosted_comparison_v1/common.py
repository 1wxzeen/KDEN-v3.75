from pathlib import Path
import os,json,hashlib,platform,importlib.metadata
import numpy as np
import s0

def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,(np.integer,)):return int(x)
 if isinstance(x,(np.bool_,)):return bool(x)
 if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
 return x

def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.tmp');tmp.write_text(json.dumps(clean(value),indent=2,sort_keys=True,allow_nan=False)+'\n');os.replace(tmp,path)

def digest(v):return hashlib.sha256(s0.canonical(clean(v))).hexdigest()
def seal(path,v):v=clean(v);v['record_sha256']=digest(v);save(path,v);return v
def read_seal(path):
 v=s0.read_json(path);s0.check_record(v);return v

def validate(root):
 r=read_seal(root/'RELEASE.json')
 for p,h in r['files'].items():s0.require(s0.sha256(root/p)==h,'Changed implementation/input snapshot: '+p)
 versions={name:importlib.metadata.version(name) for name in ['numpy','scipy','pyarrow','scikit-learn','xgboost','ngboost']}
 for name,v in {'numpy':'2.0.2','scipy':'1.15.3','pyarrow':'23.0.0','scikit-learn':'1.6.1','xgboost':'3.0.5','ngboost':'0.5.6'}.items():s0.require(versions[name]==v,'Environment mismatch: '+name)
 for line in (root/'environment.lock.txt').read_text().splitlines():
  if '==' in line:
   n,v=line.split('==');s0.require(importlib.metadata.version(n)==v,'Dependency version changed: '+n)
 return {'code_release_sha256':s0.sha256(root/'RELEASE.json'),'environment':versions,'python':platform.python_version(),'historical_not_blind':True}
