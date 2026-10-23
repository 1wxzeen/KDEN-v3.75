from pathlib import Path
import argparse,sys,os,json,platform,fcntl,subprocess,signal
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description='Frozen S5 scorecard; no refitting, gates or market access.')
parser.add_argument('command',choices=['run','validate','status','menu']);parser.add_argument('--experiment-root',type=Path,default=Path(os.environ.get('R14_EXPERIMENT_ROOT',str(ROOT.parents[1]))));parser.add_argument('--output',type=Path)
args=parser.parse_args();E=args.experiment_root.resolve();sys.path[:0]=[str(E/'src'),str(E/'implementations/s3_v1')]
import numpy as np,pyarrow,scipy,s0
from inputs import Context,save,seal,digest,verify_record_file
import workflow

def binding():
 release=verify_record_file(ROOT/'RELEASE.json')
 for rel,h in release['files'].items():s0.require(s0.sha256(s0.safe_path(ROOT,rel))==h,'S5 implementation changed')
 cfg=s0.read_json(ROOT/'config.json')
 for rel,h in cfg['parents'].items():s0.require(s0.sha256(s0.safe_path(E,rel))==h,'Frozen parent changed: '+rel)
 s0.require(np.__version__=='2.0.2' and pyarrow.__version__=='23.0.0' and scipy.__version__=='1.15.3','Use pinned modeling environment')
 return {'schema':'R14_S5_RUN_V1','s5_release_sha256':s0.sha256(ROOT/'RELEASE.json'),'parents':cfg['parents'],'environment':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,'pyarrow':pyarrow.__version__},'formal_promotion':False}

def run(out):
 out.mkdir(parents=True,exist_ok=True)
 with (out/'run.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise s0.ContractError('Another process owns this report')
  identity=binding()
  if (out/'run.json').exists():s0.require(s0.read_json(out/'run.json')==identity,'Report implementation changed; use a new output folder')
  else:save(out/'run.json',identity)
  def status(state,detail=None):
   save(out/'status.json',{'state':state,'detail':detail,'pid':os.getpid(),'updated_utc':datetime.now(timezone.utc).isoformat(),'model_fits':False})
   print(state,detail or '',flush=True)
  try:
   status('VALIDATING_FROZEN_INPUTS');ctx=Context(E,ROOT)
   if (out/'ANALYSIS_COMPLETE.json').exists():
    record=verify_record_file(out/'ANALYSIS_COMPLETE.json')
    for rel,h in record['files'].items():s0.require(s0.sha256(out/rel)==h,'Cached analysis changed')
   else:
    result=workflow.main(ctx,out,status)
    record=seal(out/'ANALYSIS_COMPLETE.json',{'result':result,'files':{p.name:s0.sha256(p) for p in out.iterdir() if p.is_file() and p.name not in ['run.json','status.json','run.lock','console.log']}})
   status('RENDERING_FIGURES')
   renderer=E/'.venv-s5-report/bin/python';s0.require(renderer.exists(),'Install the separate report environment using README instructions')
   subprocess.run([str(renderer),'-B',str(ROOT/'plots.py'),str(out)],check=True,env={**os.environ,'MPLCONFIGDIR':str(out/'.matplotlib')})
   status('WRITING_REPORT');subprocess.run([sys.executable,'-B',str(ROOT/'report.py'),str(out)],check=True)
   s0.require(binding()==identity,'Implementation changed during report')
   seal(out/'SCORECARD_RELEASE.json',{'status':'COMPLETE_WITH_DISCLOSED_TIMING_NONCONFORMANCE' if s0.read_json(out/'timing_audit.json')['status']!='PASS' else 'COMPLETE',
     'run_binding_sha256':digest(identity),'artifacts':{p.relative_to(out).as_posix():s0.sha256(p) for p in out.rglob('*') if p.is_file() and '.matplotlib' not in p.parts and p.name not in ['status.json','run.lock','console.log','SCORECARD_RELEASE.json']},'reserved_or_tail_labels_read':False,'model_fits':False,'learned_gates':False,'trading_analysis':False})
   status('COMPLETE');return {'report':str(out/'REPORT.md'),'release':str(out/'SCORECARD_RELEASE.json')}
  except BaseException as exc:status('INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAILED',str(exc));raise

def menu():
 print('S5 report\n1  Generate a new complete report\n2  Resume an interrupted report\n3  Show latest status\n4  Validate implementation\n0  Exit')
 choice=input('Choose: ').strip()
 if choice=='0':return {'status':'EXIT'}
 if choice=='4':return binding()
 if choice=='1':return run(E/'runs'/('r14-s5-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')))
 runs=sorted((E/'runs').glob('r14-s5-*'),reverse=True);s0.require(runs,'No S5 report folders')
 if choice=='3':return s0.read_json(runs[0]/'status.json')
 s0.require(choice=='2','Invalid choice')
 for i,p in enumerate(runs,1):print(i,p.name)
 i=int(input('Report number: '))-1;s0.require(0<=i<len(runs),'Invalid report');return run(runs[i])
try:
 if args.command=='menu':result=menu()
 elif args.command=='validate':result=binding()
 else:
  s0.require(args.output is not None,'--output required')
  result=run(args.output) if args.command=='run' else s0.read_json(args.output/'status.json')
 print(json.dumps(result,indent=2))
except Exception as exc:print(json.dumps({'error':str(exc)}),file=sys.stderr);sys.exit(1)
