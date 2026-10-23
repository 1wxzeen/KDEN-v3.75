from pathlib import Path
import sys,os,argparse,json,fcntl,time,traceback
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'foundation/src')]
import s0
from common import validate,save,seal
p=argparse.ArgumentParser(description='R14 boosted comparison; registered chronological training.')
p.add_argument('command',choices=['validate','probe','run','full','resume','score','status','watch','pause','menu']);p.add_argument('--project-root',type=Path,default=ROOT.parents[2]);p.add_argument('--output',type=Path);args=p.parse_args();PROJECT=args.project_root.resolve()

class Tee:
 def __init__(self,a,b):self.a=a;self.b=b
 def write(self,x):self.a.write(x);self.b.write(x);self.b.flush()
 def flush(self):self.a.flush();self.b.flush()

def execute(command,out):
 if command=='validate':return validate(ROOT)
 if out is None:raise ValueError('--output is required')
 out.mkdir(parents=True,exist_ok=True)
 if command=='status':return s0.read_json(out/'status.json')
 if command=='pause':(out/'PAUSE_REQUESTED').touch();return {'state':'PAUSE_REQUESTED','effect':'between completed fits; scoring finishes its phase'}
 if command=='watch':
  last=None
  while True:
   v=s0.read_json(out/'status.json')
   if v!=last:print(json.dumps(v,indent=2),flush=True);last=v
   if v['state'] in ['SCORED_COMPLETE','FAILED','PAUSED','INTERRUPTED','PREDICTIONS_FROZEN','PROBE_COMPLETE']:return v
   time.sleep(3)
 with (out/'run.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Another process owns this run')
  identity=validate(ROOT)
  def status(state,detail=None):
   v={'state':state,'detail':detail,'updated_utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid()};save(out/'status.json',v);print(json.dumps(v),flush=True)
  with (out/'console.log').open('a') as log:
   original=sys.stdout;sys.stdout=Tee(original,log)
   try:
    if command=='resume':(out/'PAUSE_REQUESTED').unlink(missing_ok=True)
    if (out/'PAUSE_REQUESTED').exists():raise ValueError('Run is paused; use resume')
    if command=='probe':
     import numpy as np,joblib
     from data import Data,label_cutoff
     from models import fit_model,predict_pmf
     cfg=s0.read_json(ROOT/'config.json');status('PROBE_LOADING');d=Data(ROOT,PROJECT,cfg).load(probe=True);fm=(d.dates<'2022-01-01')&d.available;qm=(d.dates>='2022-01-01')&d.available;y=d.truth(fm,'2021-12-30');results=[]
     probe_candidates=[c for c in cfg['candidates'] if (c['depth']==2 and c['rounds']==200) or (c['family']=='XGB_QUANTILE' and c['depth']==4 and c['rounds']==600) or (c['family']=='NGB_NORMAL' and c['depth']==3 and c['rounds']==600)]
     for c in probe_candidates:
      family=c['family'];status('PROBE_FITTING',c);start=time.monotonic();fit=fit_model(d.X[fm],y[fm]-d.offset[fm],d.dates[fm],c,cfg);elapsed=time.monotonic()-start;probs,point,diag=predict_pmf(fit,d.X[qm],d.offset[qm],cfg)
      path=out/(c['id']+'_probe.joblib');joblib.dump(fit,path,compress=3);loaded=joblib.load(path);p2,_,_=predict_pmf(loaded,d.X[qm],d.offset[qm],cfg);s0.require(np.allclose(probs,p2,atol=1e-12,rtol=0),'Serialization changed predictions');results.append({'candidate':c,'fit_seconds':elapsed,'fit_days':len(set(d.dates[fm])),'fit_rows':int(fm.sum()),'query_rows':int(qm.sum()),'max_pmf_sum_error':float(abs(probs.sum(axis=1)-1).max()),'diagnostics':{k:float(np.mean(v)) for k,v in diag.items()},'model_bytes':path.stat().st_size})
     seal(out/'PROBE.json',{'status':'PASS','binding':identity,'models':results,'assessment_labels_read':False,'training_truth_source_sha256':d.loader.supplement['truth_accessor']['source_sha256'],'input_hashes':d.loader.input_hashes(),'note':'Engineering probe; training timings are not full-run guarantees'});status('PROBE_COMPLETE')
    else:
     from engine import run
     if command in ['run','full','resume']:run(ROOT,PROJECT,out,status)
     if command in ['score','full','resume'] and (out/'PREDICTION_RELEASE.json').exists() and not (out/'PAUSE_REQUESTED').exists():
      from report import score
      score(ROOT,PROJECT,out,status)
    return {'output':str(out),'status':s0.read_json(out/'status.json')}
   except BaseException as exc:
    status('INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAILED',str(exc));traceback.print_exc(file=log);raise
   finally:sys.stdout=original

try:
 command=args.command;out=args.output
 if command=='menu':
  print('R14 XGBoost / NGBoost\n1  Start full training and report\n2  Resume latest run\n3  Show latest status\n4  Watch latest run\n5  Request pause between fits\n6  Validate installation\n7  Score latest frozen predictions\n0  Exit')
  choice=input('Choose: ').strip();command={'1':'full','2':'resume','3':'status','4':'watch','5':'pause','6':'validate','7':'score','0':None}[choice]
  if command is None:sys.exit(0)
  if command=='full':out=ROOT/'runs'/('r14-boost-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
  elif command!='validate':
   runs=sorted((ROOT/'runs').glob('r14-boost-*'));s0.require(runs,'No runs exist yet');out=runs[-1];print('Run:',out.name)
 print(json.dumps(execute(command,out),indent=2))
except Exception as exc:print(json.dumps({'error':str(exc)}),file=sys.stderr);sys.exit(1)
