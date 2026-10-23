"""S2 baseline run controls; never evaluate outer outcomes."""
import argparse,json,time,sys
from pathlib import Path
import numpy as np
import s0,s1
from r14_s1.data import DevelopmentLoader,as_date
from r14_s2.model import ResidualFit,mixture
from r14_s2.workflow import run,validate_run,binding,write_json


def probe(e,p):
    """Small declared development fit, no assessment labels or scores."""
    loader=DevelopmentLoader(p,e);out=[]
    for model in ['B0_H','B0_Q']:
        dates=[d for d in loader.fold_dates('OUTER_01','TRAIN','INNER_02') if as_date('2021-01-01')<=d<=as_date('2021-03-31')]
        train=loader.load_features(model,'OUTER_01','TRAIN','INNER_02',dates=dates)
        fit=ResidualFit(train,loader.training_labels(train))
        query=loader.load_features(model,'OUTER_01','ASSESS','INNER_02',dates=['2022-01-20','2022-02-20','2022-03-13'])
        started=time.monotonic();count=0;abstain=0;pool=[];discrepancy=0.
        for m,center,pmf,reason,diagnostic in fit.forecast(query,{'seasonal_half_width_days':45,'kernel_sigma_f':1.25},'scipy'):
            count+=1;abstain+=bool(reason);pool.append(diagnostic['pool_days'])
            if pmf is not None and count==1:
                ref=mixture(center,[r[1] for r in fit.pool(m,45)],1.25,'reference')
                discrepancy=float(np.max(np.abs(ref-pmf)))
                s0.require(discrepancy<1e-12,'Numerical engines disagree')
        out.append({'model':model,'training_days':len(dates),'assessment_rows':count,'abstentions':abstain,
                    'pool_days_min':min(pool),'pool_days_max':max(pool),'forecast_seconds':time.monotonic()-started,
                    'max_reference_discrepancy_first_available_row':discrepancy})
    return {'status':'PASS','purpose':'Bounded correctness and runtime probe, not tuning or evaluation','batches':out,
            'assessment_labels_returned':0,'outer_scores_computed':False,'reserved_or_tail_outcomes_returned':False,
            'source_decode_note':loader.supplement['truth_accessor']['source_physical_scope']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','validate','probe','status','watch','pause','resume'])
    parser.add_argument('--project-root',type=Path)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--max-units',type=int,help='Stop after this many newly completed units; useful bounded rehearsal')
    parser.add_argument('--engine',choices=['scipy','reference'],default='scipy')
    args=parser.parse_args();e=Path(__file__).resolve().parent.parent
    try:
        if args.command in ['status','watch','pause','resume','run'] or (args.command=='validate' and args.run_dir):
            s0.require(args.run_dir is not None,'--run-dir required')
        if args.max_units is not None:s0.require(args.max_units>0,'--max-units must be positive')
        if args.command in ['status','watch']:
            while True:
                print(json.dumps(s0.read_json(args.run_dir/'status.json'),indent=2),flush=True)
                if args.command=='status':return 0
                time.sleep(5)
        elif args.command=='pause':
            s0.require(args.run_dir.is_dir(),'Run does not exist');(args.run_dir/'PAUSE').touch()
            print('Pause requested; active atomic unit completes first.')
        else:
            s0.require(args.project_root is not None,'--project-root required')
            if args.command=='resume':(args.run_dir/'PAUSE').unlink(missing_ok=True)
            if args.command in ['run','resume']:
                run(e,args.project_root,args.run_dir,args.engine,args.max_units)
                print(json.dumps(s0.read_json(args.run_dir/'status.json'),indent=2))
            elif args.command=='probe':
                binding(e,args.project_root,'scipy')
                print(json.dumps(probe(e,args.project_root),indent=2))
            elif args.command=='validate':
                result=validate_run(e,args.project_root,args.run_dir) if args.run_dir else {'status':'VALID_IMPLEMENTATION','binding':binding(e,args.project_root,args.engine)}
                print(json.dumps(result,indent=2))
        return 0
    except KeyboardInterrupt:return 130
    except (OSError,ValueError,KeyError,ImportError) as exc:
        print(json.dumps({'status':'FAILED','reason':str(exc)}));return 1

if __name__=='__main__':sys.exit(main())
