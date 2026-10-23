"""S3 correctness probes and one registered candidate fit; no outer score command."""
from pathlib import Path
import argparse,sys,os,json,time
from collections import Counter
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('command',choices=['validate','probe','fit-unit','candidates','validate-unit'])
p.add_argument('--experiment-root',type=Path,default=Path(os.environ.get('R14_EXPERIMENT_ROOT',str(Path(__file__).resolve().parents[2]))))
p.add_argument('--project-root',type=Path)
p.add_argument('--model',choices=['ANEN','GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5'])
p.add_argument('--candidate-id');p.add_argument('--outer',default='OUTER_01');p.add_argument('--inner');p.add_argument('--output',type=Path)
args=p.parse_args();ROOT=Path(__file__).resolve().parent;E=args.experiment_root;PROJECT=args.project_root or E.parents[2]
sys.path.insert(0,str(E/'src'))
from r14_s3 import runtime
from r14_s3.data import Loader,weather
import numpy as np,s0
from r14_s1.forecast import publish_partition,read_partition
from datetime import date,timedelta

def probe():
    runtime.validate(ROOT,E,PROJECT)
    out=args.output;s0.require(out is not None and not out.exists(),'Choose a new --output directory for the probe');out.mkdir(parents=True)
    loader=Loader(PROJECT,E,ROOT);cfg=loader.s3;pc=cfg['probe'];reports=[]
    dates=[d for d in loader.fold_dates(pc['outer'],'TRAIN',pc['inner']) if (d-date(2021,1,1)).days%3==0]
    for model in runtime.MODELS:
        started=time.monotonic();train=loader.load_features(model,pc['outer'],'TRAIN',pc['inner'],dates=dates);y=loader.training_labels(train)
        query=loader.load_features(model,pc['outer'],'ASSESS',pc['inner'],dates=pc['assessment_dates'])
        parameters=pc['anen_parameters'] if model=='ANEN' else dict(pc['gam_parameters'])
        if model=='GAM_LOCATION_NORMAL':parameters['lambda_scale']=0.
        print('Fitting bounded probe:',model,flush=True)
        fitted=runtime.fit(train,y,cfg,parameters);ident=runtime.identity(ROOT,loader,model,parameters)
        records=list(runtime.records(fitted,query,parameters,ident,date(2021,12,30)))
        publish_partition(out/model,records,[m['issue_state_id'] for m in query.metadata]);read_partition(out/model)
        reports.append({'model':model,'train_days':len(dates),'train_rows':len(y),'train_complete':int(train.available.sum()),'query_rows':len(records),'statuses':dict(Counter(r['status'] for r in records)),'seconds':time.monotonic()-started,'parameters':parameters,'solver_starts':getattr(fitted,'starts',[]),
                        'feature_nonmissing_fraction':{c:float(np.isfinite(train.X[:,i]).mean()) for i,c in enumerate(train.columns)}})
    result={'status':'PASS','models':reports,'assessment_labels_read':False,'scores_computed':False,'parameter_selection_performed':False,'note':'Sparse-in-calendar bounded engineering fits; not production model performance.'};runtime.save(out/'PROBE.json',result);return result
try:
    if args.command=='validate':result=runtime.validate(ROOT,E,PROJECT)
    elif args.command=='probe':result=probe()
    elif args.command=='candidates':result=runtime.candidates(ROOT,args.model) if args.model else s0.read_json(ROOT/'candidates.json')
    elif args.command=='fit-unit':
        s0.require(args.output is not None and args.model is not None and args.candidate_id is not None,'--output, --model, --candidate-id required')
        result=runtime.unit(ROOT,E,PROJECT,args.output,args.model,args.candidate_id,args.outer,args.inner)
    else:
        s0.require(args.output is not None,'--output required');m=s0.read_json(args.output/'UNIT.json');s0.check_record(m)
        for rel,h in m['files'].items():s0.require(s0.sha256(s0.safe_path(args.output,rel))==h,'Artifact changed')
        read_partition(args.output/'forecast');result={'status':'VALID_SINGLE_UNIT','selected_model':False}
    print(json.dumps(result,indent=2,sort_keys=True))
except Exception as exc:
    print(json.dumps({'status':'FAILED','error':str(exc),'starts':getattr(exc,'starts',[])}));sys.exit(1)
