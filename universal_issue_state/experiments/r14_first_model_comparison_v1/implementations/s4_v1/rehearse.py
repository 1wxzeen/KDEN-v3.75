"""Bounded engineering rehearsal: four sparse-calendar fits, no assessment labels."""
from pathlib import Path
from datetime import date
import os, sys, time, json
ROOT=Path(__file__).resolve().parent
E=Path(os.environ['R14_EXPERIMENT_ROOT']);R=E.parents[2];S3=E/'implementations/s3_v1'
sys.path[:0]=[str(E/'src'),str(S3)]
import engine, s0
from r14_s3.data import Loader
out=Path(sys.argv[1]);s0.require(not out.exists(),'Choose a new rehearsal folder');out.mkdir(parents=True)
identity=engine.binding(ROOT,E,R);sha=engine.digest(identity);loader=Loader(R,E,S3);cfg=loader.s3;pc=cfg['probe']
dates=[d for d in loader.fold_dates(pc['outer'],'TRAIN',pc['inner']) if (d-date(2021,1,1)).days%3==0]
reports=[]
for model in engine.MODELS:
    train=loader.load_features(model,pc['outer'],'TRAIN',pc['inner'],dates=dates);y=loader.training_labels(train)
    query=loader.load_features(model,pc['outer'],'ASSESS',pc['inner'],dates=pc['assessment_dates'])
    params=pc['anen_parameters'] if model=='ANEN' else dict(pc['gam_parameters'])
    if model=='GAM_LOCATION_NORMAL':params['lambda_scale']=0.
    c=next(c for c in s0.read_json(S3/'candidates.json') if c['model_id']==model and c['parameters']==params)
    start=time.monotonic();record=engine.make_unit(out/model,train,query,y,c,cfg,S3,loader,sha,date(2021,12,30))
    verified=engine.verify_unit(out/model,sha,c)
    resumed=engine.make_unit(out/model,train,query,None,c,cfg,S3,loader,sha,date(2021,12,30))
    s0.require(record==resumed==verified,'Rehearsal resume changed unit')
    reports.append({'model':model,'status':record['status'],'training_days':len(dates),'query_rows':len(query.metadata),'seconds':time.monotonic()-start,'artifact_bytes':sum(p.stat().st_size for p in (out/model).rglob('*') if p.is_file())})
    print(model,record['status'],flush=True)
engine.write(out/'REHEARSAL.json',{'status':'PASS','units':reports,'assessment_labels_read':False,'historical_run_complete':False,'implementation_binding':identity})
