from pathlib import Path
import sys,os,argparse,json,fcntl,time
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('command',choices=['validate','probe','certify','run','score','status','pause','resume','menu']);p.add_argument('--experiment-root',type=Path,default=Path(os.environ.get('R14_EXPERIMENT_ROOT',str(ROOT.parents[1]))));p.add_argument('--output',type=Path);a=p.parse_args();E=a.experiment_root.resolve()
sys.path[:0]=[str(ROOT),str(E/'src'),str(E/'implementations/s6_v1'),str(E/'implementations/s5_v1'),str(E/'implementations/s3_v1')]
from runner import validate,run,range_mask
from inputs import Context,save,seal
import s0

def execute(command,out):
 if command=='validate':return validate(E,ROOT)
 if out is None:raise ValueError('--output is required')
 out.mkdir(parents=True,exist_ok=True)
 if command=='status':return s0.read_json(out/'status.json')
 if command=='pause':(out/'PAUSE_REQUESTED').touch();return {'status':'PAUSE_REQUESTED','effect':'between completed units'}
 with (out/'run.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Another CR1 process owns this folder')
  identity=validate(E,ROOT)
  def status(state,detail=None):
   v={'state':state,'detail':detail,'updated_utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid()};save(out/'status.json',v);print(json.dumps(v),flush=True)
  try:
   if command in ['run','resume']:
    if command=='resume':(out/'PAUSE_REQUESTED').unlink(missing_ok=True)
    if (out/'PAUSE_REQUESTED').exists():raise ValueError('Pause requested; use resume')
    run(E,ROOT,out,status)
   elif command=='score':
    from report import score
    score(E,ROOT,out,status)
   else:
    from data import certificate,load,labels
    from model import fit,predict
    import numpy as np
    reg=s0.read_json(E/'implementations/s6_v1/registration.json');ctx=Context(E,E/'implementations/s5_v1');status('CERTIFYING_BASE_LINEAGE')
    c=certificate(ctx,reg);seal(out/'BASE_REUSE_CERTIFICATE.json',{**c,'binding':identity})
    if command=='probe':
     status('BOUNDED_REAL_PROBE');d=load(ctx,reg,probe=True);days=sorted(set(d['dates']));chosen=days[:120];mask=np.isin(d['dates'],chosen)&d['common'];y=labels(ctx,d,mask,'2023-07-01',reg);results=[]
     for base in reg['base_models']:
      for name in ['R0','R1','R2']:
       start=time.monotonic();s=fit(d['designs'][base][name],(d['base'][base]['integer']==y).astype(float),d['dates'],mask,reg);pr=predict(s,d['designs'][base][name],d['common']);assert np.all((pr[d['common']]>=0)&(pr[d['common']]<=1))
       results.append({'base':base,'model':name,'converged':s['converged'],'gradient_inf':s['gradient_inf'],'seconds':time.monotonic()-start,'fit_days':s['fit_days'],'fit_rows':s['fit_rows']})
     seal(out/'PROBE.json',{'status':'PASS','engineering_probe_not_performance_evidence':True,'rows':len(d['dates']),'fit_calendar_dates':chosen,'no_assessment_performance_scored':True,'fits':results,'input_hashes':d['input_hashes'],'binding':identity})
    status('COMPLETE')
   return {'output':str(out),'status':s0.read_json(out/'status.json')}
  except BaseException as exc:status('INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAILED',str(exc));raise

try:
 if a.command=='menu':
  print('CR1 reliability\n1  Start historical fits and freeze predictions\n2  Resume latest run\n3  Show latest status\n4  Request pause after current unit\n5  Score latest frozen predictions\n6  Validate installation\n0  Exit')
  choice=input('Choose: ').strip();cmd={'1':'run','2':'resume','3':'status','4':'pause','5':'score','6':'validate','0':None}[choice]
  if cmd is None:sys.exit(0)
  if cmd=='run':out=E/'runs'/('r14-cr1-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
  elif cmd=='validate':out=None
  else:
   runs=sorted((E/'runs').glob('r14-cr1-*'));s0.require(runs,'No CR1 runs');out=runs[-1]
  result=execute(cmd,out)
 else:result=execute(a.command,a.output)
 print(json.dumps(result,indent=2))
except Exception as exc:print(json.dumps({'error':str(exc)}),file=sys.stderr);sys.exit(1)
